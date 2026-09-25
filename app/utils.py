import os
import zipfile
import xml.etree.ElementTree as ET
import re
import requests
import json
import time
import logging
import pdfplumber  # type: ignore

logging.basicConfig(level=logging.DEBUG)

MODEL_NAME = 'multi-qa-mpnet-base-dot-v1'
_model = None
_sentence_transformer_util = None


def get_model():
    """Load local embeddings only when explicitly enabled; otherwise use lexical scoring."""
    global _model, _sentence_transformer, _sentence_transformer_util
    if _model is None:
        if os.environ.get('ENABLE_LOCAL_EMBEDDINGS', '').lower() != 'true':
            _model = False
            return None
        try:
            from sentence_transformers import SentenceTransformer, util  # type: ignore
            _sentence_transformer = SentenceTransformer
            _sentence_transformer_util = util
            _model = _sentence_transformer(MODEL_NAME)
        except Exception as exc:
            logging.warning("SentenceTransformer model could not be loaded: %s. Falling back to lexical similarity.", exc)
            _model = False
    return _model if _model is not False else None

def create_upload_folders(app):
    """
    Creates the necessary upload folders for CVs and profile photos.
    If the folders already exist, it does nothing.

    Args:
        app (Flask): The Flask application instance.
    """
    os.makedirs(app.config['UPLOAD_FOLDER_CV'], exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER_PHOTOS'], exist_ok=True)

def allowed_file(filename, allowed_extensions):
    """
    Checks if a given filename has an allowed extension.

    Args:
        filename (str): The name of the file to check.
        allowed_extensions (set): A set of allowed file extensions.

    Returns:
        bool: True if the file has an allowed extension, False otherwise.
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


def extract_resume_text(file_path):
    """Extract plain text from PDF, TXT, or DOCX files for screening."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.txt':
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as handle:
            return handle.read()

    if ext == '.pdf':
        with pdfplumber.open(file_path) as pdf:
            return '\n'.join(page.extract_text() or '' for page in pdf.pages)

    if ext == '.docx':
        try:
            with zipfile.ZipFile(file_path) as zf:
                xml = zf.read('word/document.xml')
            root = ET.fromstring(xml)
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            texts = [node.text for node in root.iterfind('.//w:t', ns) if node.text]
            return ' '.join(texts)
        except Exception as exc:
            logging.warning('DOCX extraction failed: %s', exc)
            return ''

    return ''


def preprocess_text(text):
    """
    Preprocesses the input text by removing unwanted characters and normalizing spaces.

    Args:
        text (str): The text to preprocess.

    Returns:
        str: The cleaned and normalized text.
    """
    text = re.sub(r'\s+', ' ', text)  
    text = re.sub(r'[^\w\s]', '', text)  
    return text

def compute_similarity(cv_text, job_description):
    """
    Computes the cosine similarity between the CV text and job description.

    Args:
        cv_text (str): The text from the candidate's CV.
        job_description (str): The text from the job description.

    Returns:
        float: The cosine similarity score between the CV and job description.
    """
    cv_text = preprocess_text(cv_text)
    job_description = preprocess_text(job_description)

    model = get_model()
    if model is None:
        cv_tokens = set(re.findall(r'\w+', cv_text.lower()))
        job_tokens = set(re.findall(r'\w+', job_description.lower()))
        if not cv_tokens or not job_tokens:
            return 0.0
        overlap = len(cv_tokens & job_tokens)
        union = len(cv_tokens | job_tokens)
        return round((overlap / union) if union else 0.0, 4)

    embeddings_cv = model.encode(cv_text, convert_to_tensor=True)
    embeddings_job_desc = model.encode(job_description, convert_to_tensor=True)

    similarity_score = _sentence_transformer_util.cos_sim(embeddings_cv, embeddings_job_desc)

    return similarity_score.item()

def evaluate_cv(cv_text, job_description, threshold = 0.5):
    """
    Evaluates the CV against the job description using the similarity score.

    Args:
        cv_text (str): The text from the candidate's CV.
        job_description (str): The text from the job description.
        threshold (float): The similarity threshold to determine a match.

    Returns:
        bool: True if the similarity score is above the threshold, False otherwise.
    """
    similarity = compute_similarity(cv_text, job_description)
    logging.info(f"Similarity score: {similarity:.2f}")

    return similarity > threshold, similarity


def rank_resume_comparison(candidates, job_description):
    """Rank selected applications using the existing resume-match signals.

    The function accepts plain dictionaries so it can later be reused for a
    whole applicant pool without coupling bulk screening to Flask models.
    """
    job_terms = set(re.findall(r'[a-zA-Z][a-zA-Z+#.-]{2,}', job_description.lower()))
    education_terms = ('phd', 'doctorate', 'master', 'msc', 'mba', 'bachelor', 'bsc', 'degree', 'diploma')
    ranked = []

    for candidate in candidates:
        resume_text = candidate.get('resume_text', '') or ''
        resume_terms = set(re.findall(r'[a-zA-Z][a-zA-Z+#.-]{2,}', resume_text.lower()))
        matched = sorted(job_terms & resume_terms)
        missing = sorted(job_terms - resume_terms)
        years = re.findall(r'(?:\b|about\s)(\d{1,2})\+?\s+years?', resume_text.lower())
        experience_years = max((int(value) for value in years), default=0)
        role_lines = [line.strip() for line in resume_text.splitlines() if re.search(r'\b(engineer|developer|manager|analyst|designer|specialist|consultant|lead)\b', line, re.I)]
        education = [term.title() for term in education_terms if term in resume_text.lower()]
        raw_score = float(candidate.get('score', 0) or 0)
        if raw_score <= 1:
            score_percent = raw_score * 100
        elif raw_score <= 10:
            score_percent = raw_score * 10
        else:
            score_percent = raw_score
        if not score_percent and matched:
            score_percent = (len(matched) / max(len(job_terms), 1)) * 100
        ranked.append({
            **candidate,
            'match_score': round(min(100, max(0, score_percent)), 1),
            'matched_skills': matched[:12],
            'missing_skills': missing[:12],
            'experience_years': experience_years,
            'relevant_roles': role_lines[:4],
            'education': education[:4],
            'strengths': [f'Matches {len(matched)} job keywords'] + ([f'{experience_years}+ years of experience'] if experience_years else []),
            'gaps': [f'Missing: {", ".join(missing[:4])}'] if missing else ['No major keyword gaps detected'],
        })

    ranked.sort(key=lambda item: (item['match_score'], len(item['matched_skills'])), reverse=True)
    for index, candidate in enumerate(ranked, start=1):
        candidate['rank'] = index
        candidate['is_top_pick'] = bool(ranked and candidate['match_score'] == ranked[0]['match_score'])
    common_missing = sorted(set.intersection(*(set(item['missing_skills']) for item in ranked))) if ranked else []
    strong_match = bool(ranked and ranked[0]['match_score'] >= 70)
    ranking_summary = ' > '.join(item['name'] for item in ranked) or 'No candidates selected'
    explanation = f'{ranking_summary}. ' + ('The top candidate has the strongest overlap with the job requirements.' if ranked else 'Select at least two applicants to compare.')
    return {'candidates': ranked, 'strong_match': strong_match, 'common_missing': common_missing[:8], 'summary': explanation}

def generate_interview_questions(cv_text, job_description, max_retries=10):
    """
    Generates personalized interview questions based on the candidate's CV and the job description.

    Args:
        cv_text (str): The text from the candidate's CV.
        job_description (str): The text from the job description.
        max_retries (int): The maximum number of retries if the API call fails.

    Returns:
        list: A list of generated interview questions or an error message.
    """
    prompt = f"""Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
Generate 10 personalized interview questions based on the candidate's experience and the job description provided. Don't add anything else, just give the 10 questions and don't repeat questions.

### Input:
Candidate's Resume:
{cv_text}

Job Description:
{job_description}

### Response:
"""
    data = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 1000,
            "temperature": 0.6,
            "top_p": 0.9,
            "do_sample": True
        }
    }

    headers = {
        "Authorization": f"Bearer {current_app.config['API_TOKEN']}",
        "Content-Type": "application/json"
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(current_app.config['API_URL'], headers=headers, data=json.dumps(data))
            response.raise_for_status()
            result = response.json()
            logging.debug("API Response: %s", result)

            # Extract questions from the generated text
            generated_text = result[0].get('generated_text', '')
            questions = [line.strip() for line in generated_text.split("\n") if line.strip().endswith('?')]
            logging.debug("Generated Questions: %s", questions)

            # Ensure exactly 10 questions are returned
            if len(questions) == 10:
                return questions
            else:
                logging.warning("Generated questions count is not 10. Attempt %d.", attempt + 1)

        except (requests.exceptions.HTTPError, requests.exceptions.RequestException) as e:
            # Exponential backoff for retries
            wait_time = (2 ** attempt) + (0.1 * attempt)
            logging.warning(f"Attempt {attempt + 1} failed. Retrying in {wait_time:.2f} seconds... Error: {e}")
            time.sleep(wait_time)
        except Exception as e:
            logging.error(f"Unexpected error occurred: {e}")
            break

    return ["Error: Could not generate questions after multiple attempts."]

def generate_feedback(question_text, response_text, job_description, max_retries=10):
    """
    Generates feedback based on the candidate's response to an interview question, the question itself, and the job description, and generates a score out of 10 at the end.

    Args:
        question_text (str): The interview question asked to the candidate.
        response_text (str): The candidate's response to the interview question.
        job_description (str): The text from the job description.
        max_retries (int): The maximum number of retries if the API call fails.

    Returns:
        str: The generated feedback or an error message.
    """
    prompt = f"""Below is an interview question, the candidate's response, and the job description. Provide concise , short and constructive feedback on the candidate's response, considering the job requirements and the context of the question. Make sure to include a score out of 10 at the end of the feedback. The score should always be formatted as 'Score: X/10'.

    ### Example:
    Feedback: The candidate provided a well-thought-out response, addressing the key requirements of the job description effectively. However, they could improve on their technical knowledge. Score: 7/10

    ### Interview Question:
    {question_text}

    ### Candidate's Response:
    {response_text}

    ### Job Description:
    {job_description}

    ### Feedback:
    """

    data = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 500,
            "temperature": 0.6,
            "top_p": 0.9,
            "do_sample": True
        }
    }

    headers = {
        "Authorization": f"Bearer {current_app.config['API_TOKEN']}",
        "Content-Type": "application/json"
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(current_app.config['API_URL'], headers=headers, data=json.dumps(data))
            response.raise_for_status()
            result = response.json()
            logging.debug("API Feedback Response: %s", result)

            # Extract feedback from the generated text
            generated_text = result[0].get('generated_text', '')
            feedback_start = generated_text.find("### Feedback:") + len("### Feedback:")
            feedback = generated_text[feedback_start:].strip()
            logging.debug("Extracted Feedback: %s", feedback)

            return feedback

        except (requests.exceptions.HTTPError, requests.exceptions.RequestException) as e:
            # Exponential backoff for retries
            wait_time = (2 ** attempt) + (0.1 * attempt)
            logging.warning(f"Attempt {attempt + 1} failed. Retrying in {wait_time:.2f} seconds... Error: {e}")
            time.sleep(wait_time)
        except Exception as e:
            logging.error(f"Unexpected error occurred: {e}")
            break

    return "Error: Could not generate feedback after multiple attempts."


def evaluate_interview_response(question_text, response_text, job_description, resume_text='', max_retries=3):
    """Return AI-style evaluation with a score and narrative feedback, with a safe local fallback."""
    prompt = f"""Assess the candidate's answer for relevance to the role, technical depth, clarity, and alignment to the job description. Provide concise feedback and a score out of 10 formatted exactly as 'Score: X/10'.

Question: {question_text}
Candidate answer: {response_text}
Job description: {job_description}
Resume highlights: {resume_text[:1500]}
"""
    data = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 400,
            "temperature": 0.5,
            "top_p": 0.9,
            "do_sample": True,
        },
    }
    headers = {
        "Authorization": f"Bearer {current_app.config['API_TOKEN']}",
        "Content-Type": "application/json",
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(current_app.config['API_URL'], headers=headers, data=json.dumps(data), timeout=30)
            response.raise_for_status()
            result = response.json()
            generated_text = result[0].get('generated_text', '') if isinstance(result, list) and result else ''
            if generated_text:
                feedback = generated_text.strip()
                score = extract_score(feedback) or 0
                if score > 0:
                    return {'score': round(float(score), 1), 'feedback': feedback}
        except Exception as exc:
            logging.warning('AI interview evaluation failed (%s): %s', attempt + 1, exc)
            time.sleep(0.5 * (attempt + 1))

    keywords = set(re.findall(r'[a-zA-Z][a-zA-Z+#.-]{2,}', (job_description or '').lower()))
    answer_tokens = set(re.findall(r'[a-zA-Z][a-zA-Z+#.-]{2,}', (response_text or '').lower()))
    overlap = len(keywords & answer_tokens)
    score = round(min(10.0, max(0.0, (overlap / max(len(keywords), 1)) * 10 + (0.8 if len(response_text.strip().split()) > 20 else 0.4))), 1)
    if not response_text.strip():
        score = 0.0
    fallback_feedback = (
        f"The response shows {'good' if overlap else 'limited'} alignment with the role requirements. "
        f"It {'demonstrates relevant experience and structure' if score >= 6 else 'would benefit from more concrete examples and role-specific detail'}."
        f" Score: {score:.1f}/10"
    )
    return {'score': score, 'feedback': fallback_feedback}


def convert_keys_to_strings(data):
    """
    Recursively converts all dictionary keys to strings.

    Args:
        data (dict or list): The input dictionary or list to process.

    Returns:
        dict or list: The processed data with all keys converted to strings.
    """
    if isinstance(data, dict):
        return {str(k): convert_keys_to_strings(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [convert_keys_to_strings(i) for i in data]
    else:
        return data

def extract_score(feedback):
    """
    Extracts the score from the feedback text using multiple patterns.

    Args:
        feedback (str): The feedback text containing the score.

    Returns:
        int: The extracted score or None if no score was found.
    """
    patterns = [
        r'\b(\d{1,2})\s*/\s*10\b',                # Matches "3/10", "3 / 10", etc.
        r'\b(\d{1,2})\s*out\s+of\s+10\b',         # Matches "3 out of 10", etc.
        r'\b(\d{1,2})\s*over\s*10\b',             # Matches "3 over 10", etc.
        r'\bscore\s+is\s+(\d{1,2})\b',            # Matches "score is 10", "score is 3", etc.
        r'\brated\s+(\d{1,2})\s*/\s*10\b',        # Matches "rated 7/10", etc.
        r'\brating\s+of\s+(\d{1,2})\s*/\s*10\b',  # Matches "rating of 8/10", etc.
        r'\bgave\s+it\s+a\s+(\d{1,2})\b',         # Matches "gave it a 5", etc.
        r'\b(\d{1,2})\b\s+(?:points|stars)\s*/\s*10\b' # Matches "5 points / 10", "5 stars / 10", etc.
    ]

    for pattern in patterns:
        match = re.search(pattern, feedback, re.IGNORECASE)
        if match:
            return int(match.group(1))

    logging.warning("No score found in feedback.")
    return None
