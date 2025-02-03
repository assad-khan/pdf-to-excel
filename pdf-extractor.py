import streamlit as st
import pandas as pd
import pdfplumber
import json
from openai import OpenAI
from openai import APIConnectionError, RateLimitError, APIError
import traceback
import tiktoken
import re

def split_text_into_chunks(text, max_tokens, encoding):
    """Split text into chunks of up to max_tokens tokens each, preserving paragraphs where possible"""
    paragraphs = text.split('\n')
    chunks = []
    current_chunk = []
    current_token_count = 0

    for para in paragraphs:
        para_tokens = encoding.encode(para)
        para_token_count = len(para_tokens)
        
        # If adding this paragraph would exceed the limit
        if current_token_count + para_token_count > max_tokens:
            if current_chunk:
                # Add the current chunk before processing new paragraph
                chunks.append(encoding.decode(current_chunk))
                current_chunk = []
                current_token_count = 0
            
            # Handle paragraphs that are too big to fit in one chunk
            if para_token_count > max_tokens:
                # Split the big paragraph into token-limited chunks
                tokens = para_tokens
                while tokens:
                    take = min(len(tokens), max_tokens)
                    chunk_tokens = tokens[:take]
                    chunks.append(encoding.decode(chunk_tokens))
                    tokens = tokens[take:]
            else:
                # Start new chunk with current paragraph
                current_chunk = para_tokens
                current_token_count = para_token_count
        else:
            # Add paragraph to current chunk
            current_chunk.extend(para_tokens)
            current_token_count += para_token_count
            # Add newline character
            current_chunk.extend(encoding.encode('\n'))
            current_token_count += 1

    # Add the final chunk
    if current_chunk:
        chunks.append(encoding.decode(current_chunk))
    
    return chunks

def parse_page_range(page_range_str, total_pages):
    """Parse a page range string into a list of page indices"""
    if not page_range_str.strip():
        return list(range(total_pages))
    
    pages = []
    parts = page_range_str.split(',')
    
    for part in parts:
        if '-' in part:
            try:
                start, end = map(int, part.split('-'))
                start = max(1, start)
                end = min(total_pages, end)
                pages.extend(range(start-1, end))
            except:
                return []
        else:
            try:
                page = int(part)
                if 1 <= page <= total_pages:
                    pages.append(page-1)
            except:
                return []
    
    return sorted(list(set(pages)))

def extract_text(pdf_file, page_range_str):
    """Extract text from PDF with page range validation"""
    try:
        with pdfplumber.open(pdf_file) as pdf:
            total_pages = len(pdf.pages)
            page_indices = parse_page_range(page_range_str, total_pages)
            
            if not page_indices:
                st.error(f"Invalid page range: {page_range_str}")
                return None
                
            all_text = '\n'.join([pdf.pages[i].extract_text(layout=True) 
                                for i in page_indices])
            return all_text
    except Exception as e:
        st.error(f"Error extracting text: {str(e)}")
        return None

def generate_prompt(columns, instructions):
    """Create system prompt for OpenAI API"""
    prompt = f"""
    Extract structured data from the following text. Follow these requirements:
    1. Output only JSON format with a list of objects
    2. Use exactly these column names: {columns}
    3. {instructions}
    4. Maintain data types (string, number, date)
    5. Return empty string if information not available
    
    Text content:
    {{text}}
    
    JSON output:
    """
    return prompt

def extract_data_with_openai(text, columns, instructions, api_key, multiple_rows):
    """Use OpenAI to extract structured data from text with chunking"""
    if not text.strip():
        return []
    
    client = OpenAI(api_key=api_key)
    encoding = tiktoken.get_encoding("cl100k_base")
    model_name = "gpt-4o-mini" 
    model_max_tokens = 128000
    reserved_response_tokens = 2000

    try:
        prompt_template = generate_prompt(columns, instructions)
        static_prompt = prompt_template.format(text="")
        static_tokens = len(encoding.encode(static_prompt))
        
        available_tokens = model_max_tokens - static_tokens - reserved_response_tokens
        
        if available_tokens <= 0:
            st.error("Prompt is too long. Reduce columns/instructions length.")
            return []
        
        text_chunks = split_text_into_chunks(text, available_tokens, encoding)

        if not text_chunks:
            return []
        
        all_data = []
        for chunk in text_chunks:
            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[{
                        "role": "system",
                        "content": prompt_template.format(text=chunk)
                    }],
                    max_tokens=reserved_response_tokens,
                    temperature=0
                )
                
                json_str = response.choices[0].message.content
                data = []
                for x in re.findall(r'\{.*?}', json_str.replace("\n", " ")):
                    try:
                        dict_f = json.loads(x, strict=False)
                        data.append(dict_f)
                    except Exception as ex:
                       pass
                # json_str = json_str.replace("```json", "").replace("```", "").strip()
                
                # data = json.loads(json_str)
                if isinstance(data, list):
                    all_data.extend(data)
                elif isinstance(data, dict):
                    all_data.append(data)
                
            except Exception as e:
                st.error(f"Error processing chunk: {str(e)}")
                traceback.print_exc()
                continue

        if not multiple_rows and all_data:
            return [all_data[0]]
        
        return all_data
        
    except (APIConnectionError, RateLimitError, APIError) as e:
        st.error(f"OpenAI API Error: {str(e)}")
    except json.JSONDecodeError:
        st.error("Failed to parse OpenAI response")
    except Exception as e:
        st.error(f"Error during data extraction: {str(e)}")
        traceback.print_exc()
        return []
    

def set_custom_style():
    st.markdown("""
        <style>
        .stApp {
            max-width: 1200px;
            margin: 0 auto;
        }
        .st-emotion-cache-1ibsh2c {
            width: 100%;
            padding: 3rem 1rem 10rem;
            max-width: initial;
            min-width: auto;
        }
        .main-header {
            color: #2E4053;
            font-size: 36px !important;  /* Increased from 28px */
            font-weight: 700;
            text-align: center;  /* Added center alignment */
            margin: 30px 0;  /* Adjusted margin */
            padding: 10px;
        }
        .section-header {
            color: #34495E;
            font-size: 20px;
            font-weight: 600;
            margin: 20px 0 10px 0;
        }
        .card {
            background-color: #ffffff;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        /* Fix button alignment */
        .stButton {
            margin-top: 0 !important;
        }
        div[data-testid="column"] [data-testid="stVerticalBlock"] {
            gap: 0 !important;
        }
        /* Style for column tags container */
        .column-tags {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 20px;
            align-items: center;
        }
        /* Individual tag styling */
        .column-tag {
            display: inline-flex;
            align-items: center;
            background-color: #f1f3f9;
            padding: 4px 12px;
            border-radius: 4px;
            gap: 8px;
            margin-right: 8px;
        }
        .column-tag span {
            color: #333;
        }
        /* Add button styling */
        .stButton > button {
            background-color: #ff4757 !important;
            color: white !important;
            border: none !important;
            padding: 0.5rem 2rem !important;
            border-radius: 4px !important;
        }
        .stButton > button:hover {
            background-color: #ff6b81 !important;
        }
        /* Delete button styling */
        .delete-btn {
            color: #666;
            background: none;
            border: none;
            cursor: pointer;
            padding: 0px 5px;
            font-size: 16px;
        }
        .delete-btn:hover {
            color: #ff4b4b;
        }
        /* Custom styling for the file uploader */
        .uploadedFile {
            border-radius: 4px;
            padding: 10px;
            margin: 10px 0;
            background-color: #f8f9fa;
        }
        </style>
    """, unsafe_allow_html=True)

def main():
    set_custom_style()
    
    # Initialize session states
    if 'columns' not in st.session_state:
        st.session_state.columns = []
    if 'df' not in st.session_state:
        st.session_state.df = pd.DataFrame()
    
    # API Key Input in sidebar
    with st.sidebar:
        st.header("API Settings")
        api_key = st.text_input("OpenAI API Key", type="password")
    
    # App Header
    st.markdown('<p class="main-header">🔍 Smart Data Extractor</p>', unsafe_allow_html=True)
    
    with st.container():
        # Column Selection Card
        # st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<p class="section-header">📋 Select Columns</p>', unsafe_allow_html=True)
        
        # Column input with add button
        col1, col2 = st.columns([5, 1])
        with col1:
            new_column = st.text_input(
                "Add column",
                placeholder="Type column name",
                key="new_column_input",
                label_visibility="collapsed"
            )
        with col2:
            add_button = st.button("Add", type="primary", key="add_column_btn", use_container_width=True)
        
        # Handle column addition
        if new_column and (add_button or st.session_state.get('last_new_column') != new_column):
            if new_column not in st.session_state.columns:
                st.session_state.columns.append(new_column)
                st.session_state.last_new_column = new_column
                st.rerun()
        
        # Display selected columns in a grid layout
        if st.session_state.columns:
            st.markdown("### Selected Columns")
            st.markdown('<div class="column-grid">', unsafe_allow_html=True)
            
            for idx, column in enumerate(st.session_state.columns):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f'<div class="column-tag"><span>{column}</span></div>', unsafe_allow_html=True)
                with col2:
                    if st.button("✕", key=f"delete_{idx}", type="secondary", help="Delete column"):
                        st.session_state.columns.remove(column)
                        st.rerun()
            
            st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Instructions Card
        # st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<p class="section-header">📝 Extraction Instructions</p>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        with col1:
            instructions = st.text_area(
                "Special Instructions",
                placeholder="Enter any specific requirements...",
                height=100
            )
        with col2:
            page_range = st.text_input(
                "Page Range",
                placeholder="e.g., 1-3,5 (blank for all pages)"
            )
            multiple_rows = st.checkbox(
                "Extract Multiple Rows per Document",
                help="Enable this to extract multiple entries from each document"
            )
        st.markdown('</div>', unsafe_allow_html=True)
        
        # File Upload Card
        # st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<p class="section-header">📤 Upload Documents</p>', unsafe_allow_html=True)
        
        uploaded_files = st.file_uploader(
            "Drag and drop your files here",
            accept_multiple_files=True,
            type=['pdf'],
            help="Supported formats: PDF"
        )
        
        # if uploaded_files:
        #     st.markdown("### 📂 Uploaded Files")
        #     for file in uploaded_files:
        #         col1, col2, col3 = st.columns([3, 1, 1])
        #         with col1:
        #             st.text(file.name)
        #         with col2:
        #             st.text(f"Size: {file.size/1024:.1f} KB")
        #         with col3:
        #             if st.button("Remove", key=f"remove_{file.name}", type="secondary"):
        #                 # Add file removal logic here
        #                 pass
        
        # Process Button
        if uploaded_files:
            process_button = st.button(
                    "Process Files",
                    type="primary",
                )
        if uploaded_files and process_button:
            if not api_key:
                st.error("Please enter your OpenAI API key")
                return
                
            if not st.session_state.columns:
                st.error("Please add at least one column")
                return
                
            all_data = []
            progress_bar = st.progress(0)
            
            for file_idx, uploaded_file in enumerate(uploaded_files):
                if uploaded_file.type != "application/pdf":
                    st.error("Only PDF files are currently supported")
                    continue
                    
                # Extract text
                text = extract_text(uploaded_file, page_range)
                if not text:
                    continue
                
                # Extract data with OpenAI
                data = extract_data_with_openai(
                    text=text,
                    columns=st.session_state.columns,
                    instructions=instructions,
                    api_key=api_key,
                    multiple_rows=multiple_rows
                )
                
                if data:
                    for item in data:
                        item["source_file"] = uploaded_file.name
                    all_data.extend(data)
                
                progress_bar.progress((file_idx + 1) / len(uploaded_files))
            
            if all_data:
                st.session_state.df = pd.DataFrame(all_data)
                # st.success(f"Extracted {len(all_data)} records")
                
                # Show Data Preview
                st.markdown("### 📊 Extracted Data Preview")
                st.dataframe(st.session_state.df, use_container_width=True)
                
                # Download Button
                csv = st.session_state.df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="Download CSV",
                    data=csv,
                    file_name="extracted_data.csv",
                    mime="text/csv",
                    type="primary"
                )
            else:
                st.warning("No data extracted from the documents")

if __name__ == "__main__":
    st.set_page_config(
        page_title="Smart Data Extractor",
        page_icon="🔍",
        layout="wide",
        initial_sidebar_state="collapsed"
    )
    main()