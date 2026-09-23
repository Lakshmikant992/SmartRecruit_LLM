# RucRut: AI-Powered Recruitment & Resume Screening Portal
## Project Report

**Submitted by:** [Student Name, Roll No.]  
**Under the guidance of:** [Guide Name]  
**Institution:** [Institution Name]  
**Academic Year:** [Year]

---

# Chapter 1: Preliminary Material

## 1.1 Title Page

**Project Title:** RucRut: AI-Powered Recruitment & Resume Screening Portal  
**Project Type:** Web-based recruitment management and AI-assisted screening system  
**Technology Domain:** Python web development, relational data management, natural language processing, and artificial intelligence  
**Submitted by:** [Student Name, Roll No.]  
**Guide:** [Guide Name]  
**Institution:** [Institution Name]  
**Year:** [Year]

## 1.2 Certificate

This is to certify that the project report entitled **“RucRut: AI-Powered Recruitment & Resume Screening Portal”** has been prepared and submitted by **[Student Name, Roll No.]** under the guidance of **[Guide Name]** in partial fulfilment of the academic requirements of **[Programme or Course Name]** at **[Institution Name]** during **[Year]**.

The work presented in this report is considered suitable for academic evaluation.

**Guide Signature:** ____________________  
**Head of Department Signature:** ____________________  
**Date:** ____________________

## 1.3 Declaration

I/We declare that the project entitled **“RucRut: AI-Powered Recruitment & Resume Screening Portal”** is the original work carried out by **[Student Name, Roll No.]** under the supervision of **[Guide Name]**. The work has not been submitted previously, in whole or in part, for the award of any other academic qualification. All external sources, libraries, frameworks, and research materials used in the project have been acknowledged.

**Student Signature:** ____________________  
**Name:** [Student Name]  
**Date:** ____________________

## 1.4 Acknowledgement

The successful completion of this project was supported by the guidance and technical assistance of several individuals. The author expresses sincere gratitude to **[Guide Name]** for providing direction, review, and constructive feedback throughout the project. Appreciation is also extended to the faculty and staff of **[Institution Name]** for providing the academic environment and facilities required for development and evaluation.

The author further acknowledges the open-source communities behind Flask, SQLAlchemy, MongoDB, Hugging Face, Sentence Transformers, PDFPlumber, HTML, CSS, and JavaScript. These technologies provided the foundation for implementing the portal, persistence layer, document processing functions, and AI-assisted recruitment workflows.

## 1.5 Abstract

RucRut is a web-based recruitment portal designed to coordinate the interaction between administrators, recruiters, and student or candidate users through a single role-aware login system. The portal supports job creation, job discovery, candidate applications, resume upload, AI-assisted resume screening, interview-question generation, interview response evaluation, and application-status tracking.

The backend is implemented using Python and Flask. SQLAlchemy provides access to the relational database used for users, jobs, applications, interviews, and related records. MongoDB is used for selected application and evaluation documents. The frontend uses HTML, CSS, JavaScript, Jinja templates, and responsive layouts. Resume text is extracted using PDFPlumber and related document-processing utilities. Natural-language processing and transformer-based models are used to compare resume content with job descriptions and to support interview question generation and feedback.

The proposed system addresses the delay, inconsistency, and administrative effort associated with manual recruitment workflows. It centralises recruitment activities while retaining role-based access boundaries. AI output is used as decision support for screening and interview evaluation; final recruitment decisions remain under recruiter or administrator control.

**Keywords:** recruitment portal, resume screening, natural language processing, Flask, SQLAlchemy, candidate tracking, AI interview, role-based access.

## 1.6 Table of Contents

1. Preliminary Material  
2. Introduction  
3. Literature Review / Existing System  

*Chapters 4–12 will be added after confirmation to continue.*

## 1.7 List of Figures

| Figure No. | Figure Title | Page |
|---|---|---:|
| Fig. 1.1 | RucRut role-based recruitment workflow | To be assigned |
| Fig. 2.1 | Recruitment problem context | To be assigned |
| Fig. 3.1 | Existing and proposed recruitment workflow comparison | To be assigned |

## 1.8 List of Tables

| Table No. | Table Title | Page |
|---|---|---:|
| Table 1.1 | Project technology summary | To be assigned |
| Table 2.1 | Project objectives | To be assigned |
| Table 3.1 | Existing system versus proposed system | To be assigned |

### Chapter 1 Summary

This chapter identifies the project, its academic submission context, the technical domain, and the purpose of the report. It also introduces RucRut as an AI-assisted recruitment portal that combines role-based workflows, resume analysis, job applications, and interview support.

---

# Chapter 2: Introduction

## 2.1 Background

Recruitment requires coordination between organisations seeking candidates and individuals seeking employment or internships. Traditional recruitment frequently depends on manual resume review, separate communication channels, spreadsheet-based tracking, and unstructured interview evaluation. These practices become inefficient when the number of applications increases. They can also make it difficult to apply consistent screening criteria, retrieve historical application information, and provide candidates with timely status updates.

RucRut was developed as a unified recruitment portal to address these operational issues. The system provides a common application with role-aware access for administrators, recruiters, and student or candidate users. Recruiters can create and manage job postings, review applications, compare candidate resumes, and manage interview workflows. Candidates can explore job postings, submit applications, upload resumes, participate in AI-assisted interviews, and view application status. Administrators can oversee users, jobs, applications, and interview records.

The platform applies artificial intelligence as an assistive layer. Resume text is extracted from uploaded documents and compared with job descriptions to produce a screening or match score. Interview questions can be generated from the job requirements and candidate information. Interview responses can be evaluated to provide structured feedback. These outputs support human review rather than replacing recruiter judgement.

### Table 2.1: Project Technology Summary

| Layer | Technologies used in the project |
|---|---|
| Backend | Python, Flask, Flask-Migrate, Flask-Session |
| Data access | SQLAlchemy and Flask-SQLAlchemy |
| Relational persistence | SQLite or another SQLAlchemy-supported SQL database |
| Document persistence | MongoDB through PyMongo for selected application and evaluation records |
| Frontend | HTML5, CSS3, JavaScript, Jinja templates |
| AI/NLP | Hugging Face components, Transformers, Sentence Transformers, similarity-based screening utilities |
| Resume processing | PDFPlumber and document extraction utilities |
| Deployment support | Gunicorn configuration and environment-based Flask configuration |

## 2.2 Problem Statement

Recruiters and candidates require a reliable platform that can reduce repetitive recruitment administration while maintaining transparent access control and traceable application records. In a manual or fragmented process, recruiters may spend significant time reviewing resumes, candidates may lack visibility into application progress, and interview assessments may be inconsistent. Separate systems for job posting, application collection, screening, and interviews further increase operational complexity.

The problem addressed by RucRut is therefore defined as follows:

> To design and implement a unified, role-based recruitment portal that supports job management, candidate applications, resume screening, AI-assisted interviews, and application tracking while improving workflow consistency and reducing manual effort.

## 2.3 Objectives

The primary objectives of the project are:

1. To provide a single login entry point with role-based access for administrators, recruiters, and candidates.
2. To enable recruiters to create, edit, publish, and manage job postings.
3. To allow candidates to search available jobs, view job details, submit applications, and track status.
4. To extract and process resume content from supported document formats.
5. To calculate an AI-assisted match or screening score from candidate resume content and job requirements.
6. To generate interview questions using candidate and job information.
7. To support interview response evaluation and feedback for recruiter review.
8. To provide administrators with oversight of users, jobs, applications, interviews, and access permissions.
9. To maintain application and interview records in structured SQL and document-oriented storage.
10. To provide a responsive and accessible web interface across desktop, tablet, and mobile devices.

## 2.4 Scope of the Project

### 2.4.1 Functional Scope

The functional scope includes:

- User registration and sign-in through a common authentication interface.
- Role-aware navigation and access control.
- Administrator management of users, jobs, applications, and interviews.
- Recruiter job creation, editing, closure, application review, candidate comparison, screening, and interview scheduling.
- Candidate job exploration, filtering, resume submission, application creation, status tracking, profile management, and interview participation.
- Resume parsing and AI-assisted similarity or match scoring.
- AI-generated interview questions and response feedback.
- Storage of application status history, recruiter notes, interview information, and evaluation results.

### 2.4.2 Technical Scope

The system is implemented as a Flask web application using server-rendered Jinja templates and client-side JavaScript. SQLAlchemy models represent core relational entities such as `User`, `Job`, `Application`, `Interview`, `InterviewFeedback`, and `InterviewQuestionSet`. MongoDB is used for selected flexible application and interview evaluation documents. The application also includes environment-based configuration, session handling, file uploads, resume extraction, and database schema compatibility checks.

### 2.4.3 Exclusions

The project does not claim to replace human recruitment decisions. It does not guarantee that AI screening scores are free from bias or error. Production-grade identity verification, payroll integration, enterprise single sign-on, large-scale distributed deployment, and legally certified automated hiring decisions are outside the current scope.

## 2.5 Motivation

The motivation for RucRut is the need for a practical recruitment workflow that is accessible to smaller organisations, educational placement cells, and early-career candidates. A unified portal can reduce duplicate data entry, make application progress visible, and provide recruiters with structured evidence before an interview. AI-assisted processing can reduce repetitive document comparison and help prioritise recruiter attention, provided that results remain explainable and subject to human review.

## 2.6 Intended Users

| User role | Primary responsibilities in RucRut |
|---|---|
| Administrator | Manage platform users, jobs, application access, and interview oversight |
| Recruiter | Create jobs, inspect candidate applications, screen resumes, schedule interviews, and update statuses |
| Student/Candidate | Maintain a profile, upload a resume, explore jobs, apply, attend interviews, and track outcomes |

### Chapter 2 Summary

RucRut addresses the operational gap between manual recruitment processes and the need for a unified, traceable, AI-assisted workflow. Its objectives cover the complete interaction from job creation and candidate application to resume screening, interview support, and status tracking. The scope is intentionally limited to decision support and workflow management, with final recruitment authority retained by human users.

---

# Chapter 3: Literature Review / Existing System

## 3.1 Manual Recruitment and Resume Screening

In a conventional recruitment process, job descriptions are distributed through one or more channels and resumes are collected through email, forms, or separate recruitment systems. Recruiters manually inspect documents and compare candidate qualifications with job requirements. Interview notes and decisions may be recorded in spreadsheets or informal communication tools. This process can be effective for a small number of candidates but becomes difficult to scale when application volume increases.

Manual screening is also dependent on the reviewer’s time, interpretation, and consistency. Two reviewers may assign different priorities to the same resume. Important information may be overlooked when documents use different formats or terminology. Candidates may not receive a consistent view of application progress, and recruiters may have difficulty reconstructing the history of a decision.

## 3.2 Limitations of the Existing System

The limitations of a fragmented or manual recruitment system include:

1. **High screening effort:** Recruiters must read and compare a large number of resumes manually.
2. **Inconsistent evaluation:** Screening and interview assessment may vary between reviewers.
3. **Limited traceability:** Application histories, feedback, and status changes may not be maintained in one place.
4. **Delayed communication:** Candidates may not receive timely updates about their application.
5. **Duplicate data entry:** Job, candidate, and interview information may be entered repeatedly across tools.
6. **Weak role separation:** Informal workflows may expose information to users who do not require access.
7. **Limited searchability:** Resumes, applications, and interview records may be difficult to filter or compare.
8. **Low process visibility:** Recruiters and candidates may not have a shared view of the current status.
9. **Document handling problems:** Resume formats and extraction tasks may be handled inconsistently.
10. **Difficult scaling:** Manual processes do not scale efficiently with growing candidate and job volumes.

## 3.3 Proposed System

RucRut proposes a single web portal with role-based dashboards and integrated recruitment workflows. The system centralises authentication, job management, application records, resume uploads, screening, interview support, and status updates. Recruiters receive structured application and screening information, candidates receive a job exploration and tracking interface, and administrators receive oversight functionality.

The proposed system also introduces AI-assisted features. A screening utility compares extracted resume content with a job description and produces a similarity or match score. Interview-question generation uses job and candidate information to create a role-relevant question set. Response evaluation can produce scores and feedback for recruiter review. Because model outputs can be incomplete or biased, they are presented as supporting information rather than as an automatic hiring decision.

## 3.4 Existing System versus Proposed System

### Table 3.1: Existing System versus Proposed System

| Evaluation factor | Existing or manual system | Proposed RucRut system |
|---|---|---|
| Authentication | Separate or informal access channels | Single login with role-based routing |
| Job management | Documents, spreadsheets, or disconnected forms | Recruiter job creation, editing, listing, and management |
| Resume collection | Email or unstructured uploads | Candidate profile and controlled resume upload |
| Resume screening | Primarily manual review | AI-assisted resume and job-description comparison |
| Candidate comparison | Manual side-by-side review | Structured application and screening records |
| Interview preparation | Recruiter-created questions | AI-assisted, job- and candidate-aware question generation |
| Interview evaluation | Notes may be inconsistent or disconnected | Structured responses, scores, feedback, and status records |
| Application tracking | Email or spreadsheets | Candidate and recruiter status tracking with history |
| Administrator oversight | Limited or absent | User, job, application, and interview administration |
| Access control | Often informal | Role-based access boundaries in Flask routes |
| Data storage | Multiple disconnected files | SQLAlchemy relational records plus selected MongoDB documents |
| Candidate experience | Limited progress visibility | Job search, application tracking, profile, and interview views |
| Scalability | Increasing manual effort with volume | Searchable and repeatable workflow with AI-assisted prioritisation |
| Decision-making | Reviewer-dependent | Human review supported by structured AI signals |

## 3.5 Advantages of the Proposed System

The proposed system provides the following advantages:

- It combines recruitment activities in one portal.
- It reduces repetitive resume comparison work.
- It provides a consistent application record and status history.
- It improves candidate visibility into applications and interviews.
- It supports recruiter review with AI-generated screening and feedback signals.
- It separates administrator, recruiter, and candidate permissions.
- It allows the system to be extended with additional screening models, integrations, or reporting functions.

## 3.6 Risks and Responsible Use Considerations

AI-assisted recruitment must be used carefully. A similarity score measures the relationship between available text and job information; it does not measure a candidate’s complete ability, character, or potential. Resume formatting, missing information, vocabulary differences, and model limitations can affect results. The system should therefore retain human review, communicate that scores are assistive, protect candidate documents, and monitor outputs for unfair or unexpected patterns.

### Chapter 3 Summary

Manual recruitment is affected by screening effort, inconsistent evaluation, weak traceability, and limited candidate visibility. RucRut addresses these issues through a role-based portal that integrates job management, applications, resume processing, AI-assisted screening, interviews, and tracking. The proposed system improves workflow structure and efficiency while recognising that AI outputs require human oversight and responsible use.

---

## Report Status

This document contains Chapters 1–3 as requested. Chapters 4–12 will be prepared after the author confirms **continue**.
