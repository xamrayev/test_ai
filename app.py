import streamlit as st
import json
import random
from typing import Dict, Any, List, Optional
from google import genai
from google.genai import types

from google.genai.errors import APIError
import uuid # Для создания уникального ID теста

# app.py (Добавьте эту новую функцию)
import streamlit.components.v1 as components

def copy_button_html(text_to_copy: str, button_label: str, key: str):
    safe_text = json.dumps(text_to_copy)

    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8" />
    </head>
    <body>

        <button 
            id="{key}_btn"
            style="
                background-color: #f63366;
                color: white;
                padding: 8px 16px;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-size: 14px;
                width: 100%;
                transition: 0.2s;
            "
        >
            {button_label}
        </button>

        <script>
            const text_{key} = {safe_text};

            document.getElementById("{key}_btn").addEventListener("click", function() {{
                let btn = this;

                navigator.clipboard.writeText(text_{key})
                    .then(() => {{
                        btn.innerText = "✅ Скопировано!";
                        btn.style.backgroundColor = "#4CAF50";
                        
                        setTimeout(() => {{
                            btn.innerText = "{button_label}";
                            btn.style.backgroundColor = "#f63366";
                        }}, 2000);
                    }})
                    .catch(() => {{
                        btn.innerText = "❌ Ошибка копирования";
                        btn.style.backgroundColor = "#ff4444";

                        setTimeout(() => {{
                            btn.innerText = "{button_label}";
                            btn.style.backgroundColor = "#f63366";
                        }}, 2000);
                    }});
            }});
        </script>

    </body>
    </html>
    """

    components.html(html_code, height=80)

# i18
from utils import load_translation, t
lang = st.sidebar.selectbox(
    "Language / Язык / Til",
    ["en", "ru", "uz"],
    index = ["en", "ru", "uz"].index(st.session_state.get("lang", "ru"))
)


# --- 1. Структуры данных ---

# Классы для хранения перемешанных вариантов
class VariantOption(object):
    """Опция с ее новым ключом (A, B, C...) и статусом."""
    def __init__(self, key: str, text: str, is_correct: bool):
        self.key = key          
        self.text = text
        self.is_correct = is_correct

class VariantQuestion(object):
    """Вопрос в определенном варианте теста."""
    def __init__(self, text: str, options: List[VariantOption], master_id: int):
        self.text = text
        self.options = options
        self.master_id = master_id # Порядковый номер из мастер-набора
        # Находим букву правильного ответа
        self.correct_key = next(opt.key for opt in options if opt.is_correct) 

# --- 2. Session State и Утилиты ---

if 'test_data' not in st.session_state:
    st.session_state['test_data'] = None
if 'status' not in st.session_state:
    st.session_state['status'] = "INITIAL"
if 'error' not in st.session_state:
    st.session_state['error'] = None
if 'variants' not in st.session_state:
    st.session_state['variants'] = []
if 'master_request' not in st.session_state:
    st.session_state['master_request'] = {}

def get_test_schema(option_count: int) -> types.Schema:
    """Возвращает динамически созданную JSON Schema для Gemini."""
    
    question_schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "text": {"type": "string", "description": "Текст вопроса"},
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": f"{option_count} уникальных вариантов ответов."
            },
            "correct_answer_index": {
                "type": "integer",
                "description": f"Индекс (0-based) правильного ответа среди {option_count} вариантов."
            }
        },
        required=["text", "options", "correct_answer_index"]
    )
    
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "questions": {
                "type": "array",
                "items": question_schema
            }
        },
        required=["questions"]
    )

def create_test_variant(master_questions: List[Dict[str, Any]], variant_index: int) -> List[VariantQuestion]:
    """
    Создает один вариант теста, перемешивая порядок вопросов и вариантов ответов.
    """
    variant_questions = []
    
    shuffled_master = [
        (q_num, q) for q_num, q in enumerate(master_questions)
    ]
    
    # Перемешиваем порядок вопросов для всех вариантов, кроме Варианта A
    if variant_index > 0:
        random.shuffle(shuffled_master)

    for master_q_num, master_q in shuffled_master:
        options_list = master_q['options']
        correct_index_original = master_q['correct_answer_index']
        
        # Перемешивание вариантов ответа
        options_for_shuffle = list(enumerate(options_list))
        random.shuffle(options_for_shuffle)
        
        new_options = []
        
        for j, (original_index, option_text) in enumerate(options_for_shuffle):
            key = chr(65 + j)
            is_correct = (original_index == correct_index_original)
            
            new_options.append(
                VariantOption(key=key, text=option_text, is_correct=is_correct)
            )

        variant_questions.append(
            VariantQuestion(text=master_q['text'], options=new_options, master_id=master_q_num + 1)
        )
        
    return variant_questions

# --- 3. Логика Генерации ---

def generate_test(api_key: str, subject: str, topics: str, difficulty: str, q_count: int, option_count: int, num_variants: int):
    """
    Основная функция для вызова Gemini и создания вариантов.
    """
    st.session_state['status'] = "GENERATING"
    st.session_state['error'] = None
    st.session_state['test_data'] = None
    st.session_state['variants'] = []
    
    # Сохраняем запрос для дальнейшего использования в заголовках
    st.session_state['master_request'] = {
        'subject': subject, 'topics': topics, 'difficulty': difficulty
    }
    
    try:
        client = genai.Client(api_key=api_key)
        prompt_template = t("prompt_template")
        prompt = prompt_template.format(
                                        q_count=q_count,
                                        subject=subject,
                                        topics=topics,
                                        difficulty=difficulty,
                                        option_count=option_count
                                    )
        
        test_schema = get_test_schema(option_count)
        spinneri18 = t("spinner")
        
        with st.spinner(spinneri18):
            response = client.models.generate_content(
                model='gemini-2.5-pro',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=test_schema,
                    temperature=0.7
                )
            )

        # Парсинг и сохранение мастер-набора
        generated_data = json.loads(response.text)
        st.session_state['test_data'] = generated_data
        
        # Создание вариантов
        st.session_state['variants'] = []
        for i in range(num_variants):
            variant = create_test_variant(generated_data.get('questions', []), i)
            st.session_state['variants'].append(variant)

        st.session_state['status'] = "READY"

    except APIError as e:
        error_message = str(e)
        if "429 RESOURCE_EXHAUSTED" in error_message or "RESOURCE_EXHAUSTED" in error_message:
             st.session_state['error'] = (f"{t("error_429")}")
        else:
             st.session_state['error'] = f"{t("err_generate")}: {error_message}"
             
        st.session_state['status'] = "FAILED"
    except json.JSONDecodeError:
        st.session_state['error'] = f"{t("error_json")}"
        st.session_state['status'] = "FAILED"
    except Exception as e:
        st.session_state['error'] = f"{t("error_critical")}: {e}"
        st.session_state['status'] = "FAILED"

# --- 4. Генерация Markdown для Варианта ---

def get_markdown_for_variant(variant_questions: List[VariantQuestion], req_data: Dict[str, str], variant_name: str) -> str:
    """Генерирует полный Markdown для одного варианта."""
    
    unique_test_id = str(uuid.uuid4())[:8] # Сокращенный ID для печати
    md_content = f"# ID: {unique_test_id} - {t("variant")} {variant_name}\n"
    md_content += f"**{t("subject")}:** {req_data.get('subject')}\n"
    md_content += f"**{t("theme")}:** {req_data.get('topics')}\n"
    md_content += f"**{t("difficulty")}:** {req_data.get('difficulty')}\n\n"
    md_content += f"--- \n\n## {t("questions")}\n\n"
    
    answer_key = f"\n\n--- \n\n## {t("que_keys")} {variant_name}\n"
    
    for q_num, v_q in enumerate(variant_questions):
        # Вопрос с порядковым номером (который может быть перемешан)
        md_content += f"### {q_num+1}. {v_q.text}\n" 
        
        # Варианты
        for v_opt in v_q.options:
            md_content += f"- **{v_opt.key}**. {v_opt.text}\n"
        
        md_content += "\n"
        answer_key += f"- {t("question")} {q_num+1} (Master ID: {v_q.master_id}): **{v_q.correct_key}**\n"
        
    return md_content + answer_key


def get_plain_text_for_variant(variant_questions: List[VariantQuestion], req_data: Dict[str, str], variant_name: str) -> str:
    """Генерирует чистый, форматированный текст для вставки в текстовый процессор."""
    
    unique_test_id = str(uuid.uuid4())[:8] 
    plain_text = f"ID: {unique_test_id} - {t("variant")} {variant_name}\n"
    plain_text += f"{t("subject")}: {req_data.get('subject')}\n"
    plain_text += f"{t("difficulty")}: {req_data.get('difficulty')}\n"
    plain_text += "\n========================================\n\n"
    
    answer_key = f"\n\n========================================\n\n{t("que_keys")} {variant_name}\n"
    
    for q_num, v_q in enumerate(variant_questions):
        
        # Вопрос: жирный текст в Word
        plain_text += f"{q_num+1}. {v_q.text}\n" 
        
        # Варианты с отступом
        for v_opt in v_q.options:
            # Варианты: обычный текст
            plain_text += f"   {v_opt.key}. {v_opt.text}\n"
        
        plain_text += "\n" # Пустая строка между вопросами
        
        # Ключ
        answer_key += f"{t("question")} {q_num+1}: {v_q.correct_key}\n"
        
    return plain_text + answer_key

# --- 5. Интерфейс Streamlit ---
if st.session_state.get("lang") != lang:
    st.session_state["lang"] = lang
    st.session_state["translations"] = load_translation(lang)

st.set_page_config(layout="wide")
st.title(t("title"))

# --- Sidebar для ввода API Key и Параметров ---
with st.sidebar:
    st.header(t("settings"))
    
    # 1. API Key
    api_key = st.text_input("Gemini API Key", type="password", help=t("key_help"))
    
    # 2. Параметры теста
    st.subheader(t("generator_options"))
    subject = st.text_input(t("subject"), value=f"{t("temp_subject")}")
    topics = st.text_area(t("themes"), value=f"{t("temp_themes")}")
    
    difficulty = st.select_slider(
        t("difficulty"),
        options=['EASY', 'MEDIUM', 'HARD'],
        value='MEDIUM'
    )
    
    # 3. Настройка Вариантов
    st.subheader(t("setting_variation"))

    col1, col2 = st.columns(2)
    with col1:
        q_count = st.number_input(t("que_count"), min_value=1, max_value=50, value=10)
    with col2:
        option_count = st.number_input(t("que_options"), min_value=3, max_value=6, value=4)

    num_variants = st.number_input(t("variation_count"), min_value=1, max_value=10, value=3)

    # Кнопка запуска
    if st.button(t("generate_test")):
        if not api_key:
            st.error(t("no_key"))
        else:
            generate_test(api_key, subject, topics, difficulty, q_count, option_count, num_variants)
            st.rerun() 

# --- 6. Отображение Статуса и Результата ---

if st.session_state['status'] == "GENERATING":
    st.info(t("generating"))

elif st.session_state['status'] == "FAILED":
    st.error(f"{t("err_generate")} {st.session_state['error']}")
    st.session_state['status'] = "INITIAL" 

elif st.session_state['status'] == "READY" and st.session_state['variants']:
    st.success(t("done"))
    
    variants_list: List[List[VariantQuestion]] = st.session_state['variants']
    req_data = st.session_state['master_request']
    
    # st.subheader(f"Просмотр ", {len(variants_list)},"Варианты")
    
    # Создаем вкладки: Вариант A, Вариант B, Вариант C...
    tab_titles = [f"{t("variant")} {chr(65 + i)}" for i in range(len(variants_list))]
    tabs = st.tabs(tab_titles)
    
    for i, tab in enumerate(tabs):
        variant_questions = variants_list[i]
        variant_name = chr(65 + i)
        
        with tab:
            # Генерируем два формата: MD для скачивания и TEXT для копирования
            md_content_for_variant = get_markdown_for_variant(
                variant_questions, req_data, variant_name
            )
            plain_text_for_variant = get_plain_text_for_variant(
                variant_questions, req_data, variant_name
            )
            
            st.markdown(f"### {t("test_variant")} {variant_name}")
            
            # --- БЛОК СКАЧИВАНИЯ и КОПИРОВАНИЯ ---
            
            col_download, col_copy = st.columns([1, 1])

            with col_download:
                # Кнопка скачивания
                st.download_button(
                    label=f"{t("download")}",
                    data=md_content_for_variant,
                    file_name=f"test_{req_data['subject'].replace(' ', '_')}_Variant_{variant_name}.md",
                    mime="text/markdown"
                )
            
            with col_copy:
                # Кнопка копирования, использующая JS
                copy_button_html(
                    text_to_copy=plain_text_for_variant,
                    button_label=f"{t("copy")}",
                    key=f"copy_btn_{variant_name}"
                )

            st.markdown("---") 
            
            # Отображение вопросов и ключа
            answer_key_col, preview_col = st.columns([1, 4])

            with preview_col:
                st.markdown(f"#### {t("questions")}")
                for q_num, v_q in enumerate(variant_questions):
                    st.markdown(f"**{q_num+1}.** {v_q.text}")
                    
                    # Варианты
                    for v_opt in v_q.options:
                        display_text = f"**{v_opt.key}.** {v_opt.text}"
                        st.write(display_text)
                    st.markdown("---")
            
            with answer_key_col:
                st.markdown(f"#### {t("key")}")
                for q_num, v_q in enumerate(variant_questions):
                    # Показываем номер вопроса в этом варианте и его ответ
                    st.markdown(f"**{q_num+1}** (Master ID: {v_q.master_id}): **{v_q.correct_key}**")