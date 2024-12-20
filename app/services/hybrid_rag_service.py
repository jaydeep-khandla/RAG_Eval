import logging
import re
import uuid
from typing import List

from config.settings import settings
from langchain.schema import Document
from qdrant_client import QdrantClient, models
from tqdm import tqdm
from utils.const import prompt_template
from utils.llm_manager import LLMManager

# Initialize logger using LoggerFactory
logger = logging.getLogger("pipeline")


class HybridRagService:
    def __init__(self, client: QdrantClient, llm_manager: LLMManager):
        self.client = client
        self.llm_manager = llm_manager
        self.prompt_template = prompt_template

    async def index_hybrid_collection(
        self, chunks: List[Document], brain_id: str, batch_size: int = 64
    ):
        """
        Index the given list of Document chunks into the Qdrant hybrid collection.
        """
        logger.info(f"Indexing {len(chunks)} documents into Qdrant Hybrid Collection.")

        try:
            invalid_chunks = 0
            # Create batch of points of specified size for indexing.
            batched_chunks = [
                chunks[i : i + batch_size] for i in range(0, len(chunks), batch_size)
            ]

            for batch_idx, batch in enumerate(tqdm(batched_chunks, desc="Processing batches")):
                points = []
                for i, doc in enumerate(batch):
                    try:
                        # Create embeddings with fallback logic
                        dense_embedding = self.create_dense_vector(doc.page_content)
                    except Exception as e:
                        logger.exception(f"Error creating dense vector for document {i}: {e}")
                        dense_embedding = None  # Fallback to None

                    try:
                        sparse_embedding = self.create_sparse_vector(doc.page_content)
                    except Exception as e:
                        logger.exception(f"Error creating sparse vector for document {i}: {e}")
                        sparse_embedding = None  # Fallback to None

                    # Only include the point if both embeddings were created successfully
                    if dense_embedding is not None and sparse_embedding is not None:
                        points.append(
                            models.PointStruct(
                                id=str(uuid.uuid4()),
                                vector={"dense": dense_embedding, "sparse": sparse_embedding},
                                payload={"content": doc.page_content, "metadata": doc.metadata},
                            )
                        )
                    else:
                        logger.warning(f"Skipping indexing for document {i} due to failed embeddings.")
                        invalid_chunks += 1

                # Upload the batch to Qdrant
                if points:
                    self.client.upload_points(collection_name=brain_id, points=points, batch_size=batch_size)
                    logger.info(f"Indexed {len(chunks)} documents into Qdrant Hybrid Collection.")

            # Return False if any documents were skipped due to failed embeddings
            return invalid_chunks == 0
        except Exception as e:
            logger.exception(f"Error occurred during batch indexing: {e}")
            return False

    def create_dense_vector(self, text: str):
        """
        Create a dense vector from the text using the dense embedding model.
        """
        try:
            embeddings = settings.DENSE_EMBEDDING_MODEL.embed_query(text)
            return embeddings
        except Exception as e:
            raise e

    def create_sparse_vector(self, text: str):
        """
        Create a sparse vector from the text using the sparse embedding model.
        """
        try:
            embeddings = list(settings.SPARSE_EMBEDDING_MODEL.embed([text]))[0]
            return models.SparseVector(
                indices=embeddings.indices.tolist(), values=embeddings.values.tolist()
            )
        except Exception as e:
            raise e

    def hybrid_search(self, query: str, selected_pdf_id: str, brain_id: str, limit=20):
        """
        Perform a hybrid search based on the provided query.
        """
        logger.info(f"Performing hybrid search for the selected pdf")

        try:
            dense_query = self.create_dense_vector(query)
            sparse_query = self.create_sparse_vector(query) 

            results = self.client.query_points(
                collection_name=brain_id,
                prefetch=[
                    models.Prefetch(query=sparse_query, using="sparse", limit=limit),
                    models.Prefetch(query=dense_query, using="dense", limit=limit),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="metadata.pdf_id",
                            match=models.MatchValue(value=selected_pdf_id),
                        )
                    ]
                ),
                limit=limit,
            )

            documents = [point for point in results.points]

            # ReRank the documents
            reranked_docs = self.llm_manager.rerank_docs(documents, query)

            logger.info(f"Results generated: {len(reranked_docs)} documents retirved")
            return reranked_docs
        except Exception as e:
            raise e

    def sparse_search(self, query: str, pdf_id: str, brain_id: str):
        """
        Perform a sparse search based on the provided query using QdrantVectorStore.
        """
        try:
            # Generate sparse query
            sparse_query = list(settings.SPARSE_EMBEDDING_MODEL.embed([query]))[0]
            sparse_query = models.SparseVector(
                indices=sparse_query.indices.tolist(), values=sparse_query.values.tolist()
            )

            logger.info("Begin sparse Search")

            results = self.client.query_points(
                collection_name=brain_id,
                query=sparse_query,
                using="sparse",
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="metadata.pdf_id", match=models.MatchValue(value=pdf_id)
                        )
                    ]
                ),
            )
            documents = [point for point in results.points]

            logger.info(
                f"Sparse Search Completed. Result: {len(documents)} documents retrieved"
            )
            return documents
        except Exception as e:
            raise e

    def generate_response(self, question: str, context: str):
        """
        Generate a response using the LLMManager and prompt template.
        """
        try:
            # Format the prompt using the provided template
            formatted_prompt = self.prompt_template.format(
                question=question, context=context
            )

            # Call the invoke method with the formatted prompt string
            response = self.llm_manager.llm.invoke(formatted_prompt)
            logger.info("response generated")
            return response
        except Exception as e:
            raise e
