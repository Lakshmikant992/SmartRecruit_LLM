# **RucRut - Intelligent Recruitment Optimization System**

## **Overview**
RucRut is an advanced AI-powered recruitment system designed to enhance and streamline the hiring process for both **job providers** and **candidates**. The platform leverages cutting-edge **Natural Language Processing (NLP)** and **AI models** to generate tailored interview questions based on the candidate’s CV and job requirements, automatically evaluate their responses, and provide comprehensive feedback.

This system is built using **Flask**, **SQLAlchemy**, **MongoDB**, and **Hugging Face's NLP models**, with a focus on offering efficient, bias-reducing, and personalized recruitment experiences.

---

## **Features**

### **For Job Providers**
- **Dashboard**: Manage job postings and track candidate applications in real-time.
- **Job Posting Creation**: Create and modify job postings with detailed specifications.
- **AI-Generated Interview Questions**: Automatically generate interview questions based on candidate CV and job description.
- **Automatic Feedback and Scoring**: Receive AI-driven feedback and score candidates based on their interview responses.
- **Analytics and Reports**: View candidate performance metrics through various graphs, such as age distribution, score comparisons, and top performers.

### **For Candidates**
- **Job Search and Application**: Browse and apply for job postings in just a few clicks.
- **AI-Powered Interviews**: Experience tailored interview questions based on your CV and the specific job requirements.
- **Immediate Feedback**: Get real-time feedback on interview responses to improve performance.

---

## **Setup and Installation**

To set up the RucRut application locally, follow these steps:

### **Requirements**
- **Python 3.11+**
- **Flask 2.2.3**
- **MongoDB 4.7.0**
- **SQLAlchemy 2.0.8**

### **Steps**
1. **Obtain the repository**:
   ```bash
   git clone git@github.com:Lakshmikant992/RucRut.git
   cd RucRut
   ```

2. **Install required packages**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**:
   - Ensure to configure your `.env` file with the necessary environment variables for the Flask application, MongoDB connection, and Hugging Face API credentials.

4. **Initialize the database**:
   - Set up your SQLite database:
     ```bash
     flask db upgrade
     ```

5. **Run the Flask application**:
   ```bash
   flask run
   ```
   The application will be available on `http://localhost:5000`.

6. **Access MongoDB**:
   - Ensure MongoDB is running, and it's properly configured in the `.env` file.

---

## **How to Use the Application**

### **Job Providers**
1. **Sign up and Log in**.
2. **Create Job Postings**: Add jobs with specific titles, locations, descriptions, and other necessary information.
3. **Manage Applications**: Review candidates’ CVs, interview responses, and scores.
4. **Track Data**: Use the dashboard to view visual insights such as the top 3 candidates, score comparisons, and other analytics.

### **Candidates**
1. **Browse Jobs**: Search and apply for jobs that match your skills.
2. **AI Interview**: Participate in personalized interviews generated based on your CV.
3. **Get Feedback**: Receive instant feedback and improve based on AI evaluations.

---

## **Technologies Used**

- **Backend**: Flask, SQLAlchemy, MongoDB
- **Frontend**: HTML5, CSS3, JavaScript
- **AI Models**: Hugging Face Transformers, Sentence Transformers
- **PDF Parsing**: PDFPlumber

---

## **Contributing**

We welcome contributions to improve the functionality of RucRut. If you'd like to contribute, please:

1. Fork the repository.
2. Create a new branch for your feature/bug fix.
3. Submit a pull request.

---

## **License**

This project is licensed under the **3DSF License**.

---

## **SmartRecruit_LLM**

This project is also available on GitHub: [SmartRecruit_LLM](https://github.com/Lakshmikant992/SmartRecruit_LLM.git)

## Free-tier deployment

The repository includes `render.yaml` for a single Render Web Service. Because the
frontend is server-rendered Flask/Jinja, the same HTTPS service serves the pages and
the API; no separate JavaScript frontend build is required.

Recommended free-tier services:

- **Application:** Render Free Web Service
- **Relational database:** Neon Free PostgreSQL
- **Document database:** MongoDB Atlas Free cluster

Create the Neon and Atlas databases first, then create the Render service from this
repository. Configure the following Render environment variables without committing
their values:

`SECRET_KEY`, `DATABASE_URL`, `MONGO_URI`, `MONGO_DB_NAME`, `API_TOKEN`,
`APP_ENV=production`, `SESSION_TYPE=filesystem`, `CORS_ORIGINS`, and
`MAX_CONTENT_LENGTH=16777216`.

Render uses `pip install -r requirements.txt` to build and
`gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 120 run:app` to
start. The health check is `/healthz`. The application creates missing relational
tables on startup and applies its existing additive schema checks; there is no
committed Flask-Migrate revision history yet, so review a production schema migration
before changing existing tables.

Free Render filesystems are ephemeral, so uploaded CVs, profile photos, and local
filesystem sessions are not durable across restarts. Use object storage and Redis
before treating this as a production system with persistent uploads or shared sessions.
Render Free Web Services also sleep after inactivity, and Neon Free and MongoDB Atlas
Free have storage, compute, and throughput limits. See `.env.example` for local
variable names and `render.yaml` for the deployment contract.

---