from config.settings import settings
from qdrant_client import QdrantClient
from langchain.schema import Document
from langchain_qdrant import QdrantVectorStore
from config.logging_config import LoggerFactory  
from utils.llm_manager import LLMManager
from RAG_Eval.app.utils.collection import Collection
from uuid import uuid4
from typing import List


# Initialize logger using LoggerFactory
logger_factory = LoggerFactory()
logger = logger_factory.get_logger("pipeline")

class HyDEService:
    
    def __init__(self, client: QdrantClient):
        self.client = client
        self.llm_manager = LLMManager()  
        self.prompt_template = """You are an AI assistant for answering questions about the various documents from the user.
        You are given the following extracted parts of a long document and a question.If you are not provided with any extracted
        parts of the documments then try to generate an answer based on your knowledge and facts in your knowledge. Remember to provide a conversational answer.
        If you don't know the answer, just say "Hmm, I'm not sure." Don't try to make up an answer.
        Question: {question}
        =========
        {context}
        =========
        Answer in Markdown: """
        # self.collection = Collection(client)
        # self.vector_store = QdrantVectorStore(
        #     client=self.client, 
        #     collection_name=settings.DENSE_COLLECTION, 
        #     embedding = settings.DENSE_EMBEDDING_MODEL,
        #     vector_name= "dense",
        # )        
        # self.retriever = self.vector_store.as_retriever(search_type="mmr")

    async def index_collection(self, chunks: List[Document]):
        """
        Index the given list of Document chunks into the Qdrant dense collection.
        """
        uuids = [str(uuid4()) for _ in range(len(chunks))]
        self.vector_store.add_documents(documents=chunks, ids= uuids)

    def hyde_search(self, query: str):
        """
        Perform a HyDE search based on the provided query using QdrantVectorStore.
        """
        results = self.retriever.invoke(query)
        return results

    def generate_response(self, question: str, context: str):
        """
        Generate a response using the LLMManager and prompt template.
        """
        formatted_prompt = self.prompt_template.format(question=question, context=context)

        response = self.llm_manager.llm.invoke(formatted_prompt)
        return response
