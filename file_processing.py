import io
import ollama  # Используйте локальную функцию или API вызов, если требуется
import docx
from PyPDF2 import PdfReader
from PIL import Image
import pytesseract
import json

def read_pdf(file):
    pdf = PdfReader(file)
    text = "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])
    return text

def read_image(file):
    img = Image.open(file)
    return pytesseract.image_to_string(img)

def read_docx(file):
    doc = docx.Document(file)
    return "\n".join([para.text for para in doc.paragraphs])

def read_txt(file):
    return file.read().decode("utf-8")

def process_file(file, mime_type):
    if mime_type == "application/pdf":
        return read_pdf(file)
    elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return read_docx(io.BytesIO(file.getvalue()))
    elif mime_type == "text/plain":
        return read_txt(file)
    elif mime_type in ["image/jpeg", "image/png"]:
        return read_image(file)
    else:
        return "Unsupported file format"

def get_answer(question, context):
    prompt = f"Context: {context}\n\nQuestion: {question}\n\nAnswer:"
    response = ollama.generate(model="llama2", prompt=prompt)
    return response.get("response", "Нет ответа")

def generate_summary(context):
    prompt = f"Создай конспект и дай советы по дополнительным ресурсам для этого материала:\n{context}"
    response = ollama.generate(model="llama2", prompt=prompt)
    return response.get("response", "")

def generate_task(context):
    prompt = f"Создай задание по следующему материалу:\n{context}\nВерни задание в ясном и кратком формате."
    response = ollama.generate(model="llama2", prompt=prompt)
    return response.get("response", "Не удалось сгенерировать задание.")

def generate_quiz(context):
    prompt = (
        f"Создай квиз с 4 вариантами ответа по следующему материалу:\n{context}\n\n"
        "Верни ответ строго в формате JSON, без лишнего текста. Формат:\n"
        "{\"question\": \"Вопрос\", \"options\": [\"вариант1\", \"вариант2\", \"вариант3\", \"вариант4\"], \"correct_index\": 0}"
    )
    response = ollama.generate(model="llama2", prompt=prompt)
    return response.get("response", "{}")

from langchain.llms.base import LLM
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain.memory import ConversationBufferMemory

class OllamaLLM(LLM):
    @property
    def _llm_type(self) -> str:
        return "ollama"
    
    @property
    def _identifying_params(self):
        return {"model": "llama2"}
    
    def _call(self, prompt: str, stop=None) -> str:
        result = ollama.generate(model="llama2", prompt=prompt)
        return result.get("response", "Нет ответа")
    
    def __call__(self, prompt: str, stop=None) -> str:
        return self._call(prompt, stop=stop)

memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
prompt_template = PromptTemplate(
    template="Context: {context}\n\nQuestion: {question}\n\nAnswer:",
    input_variables=["context", "question"]
)
llm = OllamaLLM()
chain = LLMChain(llm=llm, prompt=prompt_template, memory=memory)

def get_answer_chain(question, context):
    return chain.run(context=context, question=question)
