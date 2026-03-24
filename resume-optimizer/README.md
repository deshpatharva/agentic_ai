# Resume Optimizer — AI-Powered Pipeline

A full-stack application that uses a multi-agent AI pipeline (powered by Anthropic Claude) to analyze, rewrite, humanize, and score resumes against a target job description.

## Features

- **Upload** PDF or DOCX resumes
- **JD Analysis**: Extracts keywords using spaCy, TF-IDF, and Claude
- **Multi-agent Pipeline**:
  - Rewriter Agent: Aligns resume with JD keywords
  - Humanizer Agent: 3-step polish (humanize → critic → humanize)
  - 4 Scorers: ATS Match, Impact, Skills Gap, Readability
- **Optimization Loop**: Automatically iterates (up to 5x) until average score ≥ 90
- **Real-time SSE**: Live progress streaming to the frontend
- **DOCX Output**: Downloads a formatted, optimized resume

## Architecture

```
resume-optimizer/
├── backend/
│   ├── main.py                  # FastAPI app, SSE endpoints
│   ├── agents/
│   │   ├── jd_analyzer.py       # spaCy + TF-IDF + Claude keyword extraction
│   │   ├── rewriter.py          # Claude resume rewriter
│   │   ├── humanizer.py         # Claude humanizer (3-step loop)
│   │   └── scorer.py            # ATS (pure Python) + 3 Claude scorers
│   ├── parsers/
│   │   ├── pdf_parser.py        # pdfplumber PDF parser
│   │   └── docx_parser.py       # python-docx DOCX parser
│   └── generators/
│       └── docx_generator.py    # python-docx DOCX generator
└── frontend/
    ├── src/
    │   ├── App.jsx              # Main app with SSE state management
    │   └── components/
    │       ├── UploadZone.jsx   # Drag-and-drop file upload
    │       ├── JDInput.jsx      # JD textarea + keyword chips
    │       ├── PipelineProgress.jsx  # Stage stepper
    │       ├── AgentLog.jsx     # Real-time color-coded event log
    │       └── ScoreDashboard.jsx    # 4 score cards + download
    └── package.json
```

## Setup

### 1. Install Python dependencies

```bash
cd resume-optimizer
pip install -r requirements.txt
```

### 2. Download spaCy model

```bash
python -m spacy download en_core_web_sm
```

### 3. Set Anthropic API key

```bash
# Linux/macOS
export ANTHROPIC_API_KEY=sk-ant-...

# Windows (PowerShell)
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# Windows (CMD)
set ANTHROPIC_API_KEY=sk-ant-...
```

### 4. Run the backend

```bash
# From the resume-optimizer/ directory
uvicorn backend.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.
Interactive API docs: `http://localhost:8000/docs`

### 5. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

The UI will be available at `http://localhost:5173`.

## Usage

1. **Upload Resume**: Drag and drop a `.pdf` or `.docx` resume file into the upload zone
2. **Paste Job Description**: Copy the full job description into the text area
3. **Analyze JD** (optional): Click "Analyze Job Description" to preview extracted keywords
4. **Start Pipeline**: Click "Start Optimization Pipeline" to begin
5. **Monitor Progress**: Watch real-time agent activity in the log panel and stage stepper
6. **Review Scores**: See ATS, Impact, Skills Gap, and Readability scores update live
7. **Download**: When the pipeline completes, click "Download Optimized Resume (.docx)"

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/upload` | Upload and parse a resume file |
| POST | `/analyze-jd` | Extract keywords from a job description |
| POST | `/run-pipeline` | Start the optimization pipeline |
| GET | `/status/{job_id}` | SSE stream of pipeline progress |
| GET | `/download/{job_id}` | Download the optimized .docx |

## Pipeline Flow

```
Upload & Parse
     ↓
JD Analysis (spaCy + TF-IDF + Claude)
     ↓
┌─── Rewrite Resume (Claude) ───────────────────┐
│    ↓                                           │
│    Humanize (Claude 3-step loop)               │
│    ↓                                           │
│    Score: ATS + Impact + Skills + Readability  │
│    ↓                                           │
│    Average ≥ 90 or 5 iterations? → Yes → Done  │
│    ↓ No                                        │
│    Consolidate feedback → loop back ───────────┘
↓
Generate .docx output
```

## Requirements

- Python 3.10+
- Node.js 18+
- Anthropic API key (Claude access required)
- Internet connection for Claude API calls
