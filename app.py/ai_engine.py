import os
import requests
import json
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_core.messages import AIMessage, HumanMessage

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = "nomic-embed-text:latest"
LLM_MODEL = "llama3:latest" # Fallback to mistral if mistral exists

# Initialize DB Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROMA_DIR = os.path.join(BASE_DIR, "instance", "chroma_db")
UPLOAD_DIR = os.path.join(BASE_DIR, "instance", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

class AIEngine:
    def __init__(self):
        self.embeddings = None
        self.vector_store = None
        self._initialize_ai()

    def _initialize_ai(self):
        """Safely verify Ollama availability and initialize LangChain embeddings and ChromaDB"""
        try:
            # Check if Ollama is reachable
            resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                # Pick model based on availability
                global LLM_MODEL
                if "mistral:latest" in models and "llama3:latest" not in models:
                    LLM_MODEL = "mistral:latest"
                elif "llama3:latest" in models:
                    LLM_MODEL = "llama3:latest"
                else:
                    # If models aren't pulled yet, try to pull or default to whatever is there
                    if models:
                        LLM_MODEL = models[0]
                
                # Check for embeddings model
                if EMBED_MODEL not in models:
                    # Fallback to local OllamaEmbeddings anyway, it will pull automatically or raise a warning
                    pass

                self.embeddings = OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_URL)
                self.vector_store = Chroma(
                    persist_directory=CHROMA_DIR,
                    embedding_function=self.embeddings,
                    collection_name="globetrotter_rag"
                )
        except Exception as e:
            print(f"Warning: Local Ollama check failed: {e}. AI features will run in mock mode.")
            self.embeddings = None
            self.vector_store = None

    def is_available(self):
        """Returns True if Ollama is connected and loaded"""
        return self.embeddings is not None

    def query_ollama(self, prompt, system_prompt="You are a helpful travel assistant."):
        """Query local Ollama directly via HTTP requests for fast execution"""
        if not self.is_available():
            return self._mock_llm_response(prompt)
        
        try:
            payload = {
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "options": {
                    "temperature": 0.7
                }
            }
            resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=60)
            if resp.status_code == 200:
                return resp.json()["message"]["content"]
            else:
                return f"Ollama returned error: {resp.status_code} - {resp.text}"
        except Exception as e:
            return self._mock_llm_response(prompt, error=str(e))

    def ingest_document(self, file_path):
        """Load, split, and ingest a PDF/TXT guide into local ChromaDB"""
        if not self.is_available() or not self.vector_store:
            return False, "Ollama/ChromaDB is not active."
        
        try:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == ".pdf":
                loader = PyPDFLoader(file_path)
            else:
                loader = TextLoader(file_path, encoding="utf-8")
            
            docs = loader.load()
            splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=150)
            chunks = splitter.split_documents(docs)
            
            # Inject metadata
            filename = os.path.basename(file_path)
            for chunk in chunks:
                chunk.metadata["source"] = filename
                
            self.vector_store.add_documents(chunks)
            return True, f"Successfully indexed {len(chunks)} text chunks."
        except Exception as e:
            return False, f"Ingestion error: {str(e)}"

    def similarity_search(self, query, k=3):
        """Search vector database for top matching travel guides context"""
        if not self.is_available() or not self.vector_store:
            return []
        try:
            results = self.vector_store.similarity_search(query, k=k)
            return [{"text": doc.page_content, "source": doc.metadata.get("source", "Unknown")} for doc in results]
        except Exception as e:
            print("ChromaDB search failed:", e)
            return []

    def travel_chat(self, user_message, chat_history, context_docs=[]):
        """Conduct multi-turn chat with vector context memory"""
        system_prompt = (
            "You are GlobeTrotter AI, an advanced, premium offline AI travel assistant. "
            "Help the user plan their dream itineraries, discover hidden gems, allocate budgets, "
            "suggest local culture, packing lists, and offer travel insights. "
            "Use the provided context documents if applicable. Keep recommendations realistic, specific, and exciting."
        )
        
        # Build memory block
        history_block = ""
        for msg in chat_history[-6:]:  # Keep last 6 messages
            role = "User" if msg["role"] == "user" else "AI"
            history_block += f"{role}: {msg['content']}\n"
            
        # Build context block
        context_block = ""
        if context_docs:
            context_block = "\nRelevant guides context:\n"
            for doc in context_docs:
                context_block += f"--- Source: {doc['source']} ---\n{doc['text']}\n"

        prompt = (
            f"{context_block}\n"
            f"Conversation History:\n{history_block}"
            f"User: {user_message}\n"
            f"AI:"
        )
        
        return self.query_ollama(prompt, system_prompt=system_prompt)

    def generate_day_wise_itinerary(self, destination, duration_days, budget, style):
        """Generate formatted day-wise travel itinerary"""
        prompt = (
            f"Generate a highly detailed, premium, day-wise travel itinerary for a {duration_days}-day trip to {destination}. "
            f"Travel Style: {style} (e.g. Solo, Family, Honeymoon, Adventure, Luxury, Backpacking). "
            f"Estimated Budget: {budget} USD.\n"
            f"For each day, structure it exactly with:\n"
            f"- **Morning Activities**\n"
            f"- **Afternoon Activities**\n"
            f"- **Evening Activities**\n"
            f"- **Rest Periods & Smart Travel Tips**\n"
            f"Provide cost estimations and prioritize activities matching the budget. Suggest local cultural spots and hidden gems."
        )
        system_p = "You are a professional travel planner. Return markdown-formatted, detailed itineraries."
        return self.query_ollama(prompt, system_prompt=system_p)

    def generate_packing_list(self, destination, duration_days, style):
        """Suggest clothing, electronics, medicine, and essential packing checklists"""
        prompt = (
            f"Create a packing checklist for a {duration_days}-day trip to {destination} with a '{style}' travel style.\n"
            f"Provide items under the following categories:\n"
            f"1. Clothing\n"
            f"2. Electronics\n"
            f"3. Medicine & Toiletries\n"
            f"4. Essentials & Miscellaneous\n\n"
            f"Format the output strictly as a JSON object, with the categories as keys and an array of items as values, like this:\n"
            f"{{\n"
            f"  \"Clothing\": [\"Item 1\", \"Item 2\"],\n"
            f"  \"Electronics\": [\"Item 1\", \"Item 2\"],\n"
            f"  \"Medicine & Toiletries\": [\"Item 1\", \"Item 2\"],\n"
            f"  \"Essentials & Miscellaneous\": [\"Item 1\", \"Item 2\"]\n"
            f"}}\n"
            f"Do not include any other conversational text, headers, or markdown formatting outside of the JSON block."
        )
        system_p = "You are a professional packing assistant. You respond only with valid JSON structures as requested."
        return self.query_ollama(prompt, system_prompt=system_p)

    def analyze_expenses_and_suggest(self, expenses, total_budget):
        """Provide detailed offline budget warnings, health score, and cost-saving tips"""
        total_spent = sum(exp.get("amount", 0) for exp in expenses)
        categories = {}
        for exp in expenses:
            cat = exp.get("category", "Others")
            categories[cat] = categories.get(cat, 0) + exp.get("amount", 0)
            
        categories_str = ", ".join([f"{c}: ${amt:.2f}" for c, amt in categories.items()])
        
        prompt = (
            f"Analyze these travel expenses: Total Budget: ${total_budget:.2f}, Total Spent: ${total_spent:.2f}. "
            f"Categorized Costs: {categories_str}.\n"
            f"Please output a brief structured evaluation containing:\n"
            f"1. **Budget Health Score**: 0 to 100.\n"
            f"2. **Warnings/Insights**: Is the spending rate too fast? Which category is dominating?\n"
            f"3. **Cheapest Trip Alternatives / Cost-Saving Tips**: Suggest specific local/practical hacks to save money on Transport, Food, or Activities.\n"
            f"4. **Predicted Total Cost Forecast** based on current trajectory."
        )
        system_p = "You are a travel finance analyst. Keep reports concise, smart, and direct."
        return self.query_ollama(prompt, system_prompt=system_p)

    def _mock_llm_response(self, prompt, error=""):
        """Graceful offline placeholder mock responses if Ollama is not running"""
        prompt_lower = prompt.lower()
        
        # Check type of prompt
        if "itinerary" in prompt_lower:
            return (
                "### Day 1: Exploring Core Attractions\n"
                "* **Morning**: Walking tour of historic city center. Experience local breakfast at street side bistros. ($15)\n"
                "* **Afternoon**: Major museum visit and park stroll. ($25)\n"
                "* **Evening**: Sunset dining at a panoramic vantage point. ($40)\n"
                "* *Tip*: Buy a 24-hour travel pass to save transit costs.\n\n"
                "### Day 2: Culture & Neighborhood Exploration\n"
                "* **Morning**: Visit local open-air markets and check out historical landmarks. ($10)\n"
                "* **Afternoon**: Discover hidden alleys, artisan shops, and enjoy a traditional lunch. ($20)\n"
                "* **Evening**: Attend a local cultural show or music event. ($35)\n"
                "* *Tip*: Travel outside peak hours to beat the crowd."
            )
        elif "packing" in prompt_lower:
            return (
                "Clothing: Comfortable walking shoes, Weather-appropriate layers, Light rain jacket, Casual outfits\n"
                "Electronics: Universal travel adapter, Power bank, Charger cables, Camera\n"
                "Medicine: Pain relievers, Motion sickness pills, First-aid bandages, Personal prescriptions\n"
                "Essentials: Passport copy, Emergency cash, Reusable water bottle, Travel insurance card"
            )
        elif "expense" in prompt_lower or "budget" in prompt_lower:
            return (
                "### Budget Evaluation Report\n"
                "* **Budget Health Score**: 85/100 (Looking good!)\n"
                "* **Insights**: Your spending on accommodations is stable. Activity budgets are slightly elevated.\n"
                "* **Cost-Saving Tips**: Opt for public transit cards, explore free museum admission days, and dine in local residential boroughs instead of tourist centers.\n"
                "* **Forecast**: Projecting a saving of about 10% under total budget."
            )
        else:
            return (
                "Hello! I am GlobeTrotter AI. Ollama is currently offline or loading. "
                "Here is an automated travel suggestion: Always try to plan stops chronologically, "
                "keep a digital copy of your travel documents in your journal, and allocate at least "
                "15% of your budget for emergency expenses. How else can I assist you today?"
            )

ai_engine = AIEngine()
