# AI Data Analyst

Python · pandas · Streamlit · Plotly · Qwen (via xKiro) · pytest

A streamlit app that answers plain language questions about a CSV file,
built on one rule:
**The model proposes, Python decides what runs.**
The model understands the question and chooses one of six approved
analysis tools. The code checks every choice and runs pandas code written in
advance. Nothing the model writes is run as code.

---

## Goal and user 

**Target user**: A business user (sales, operations,management) who has a CSV file but cannot write Pandas queries.

**Goal**: In one visit, upload a CSV file, check that it loaded correctly, ask few questions, and give reliable answers (a sentence, a number, a small table, a chart when needed, and the filters applied).

---

## Setup

### Get the project

```bash
git clone https://github.com/demaabukwaik-dev/ai-data-analyst.git
cd ai-data-analyst
```

### Requirements

- Python 3.11 or newer.
  - On Windows, install it from https://www.python.org/downloads/.
  - On Ubuntu / WSL, run `sudo apt install python3 python3-venv`.

- An API key for the model service. The app uses the free Qwen model
  (`qwen/qwen3.6-35b-a3b:free`) through [xKiro](https://xkiro.com):
  sign in and create an API key.
  - The key goes in `.streamlit/secrets.toml`, which you create from
    `.streamlit/secrets.toml.example` (see below).
  - The service address and the model name are in `agent/config.py`
    (`API_BASE`, `API_MODEL`). Any service that uses the OpenAI API format
    works if you change them.

### Linux / WSL / macOS

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

### Windows (PowerShell)

```powershell
py --version
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .streamlit\secrets.toml.example .streamlit\secrets.toml
```

### API key

Open `.streamlit/secrets.toml` and replace the placeholder with your key:

```toml
API_KEY = "your-key-here"
```

---

## How to run

```bash
streamlit run app.py
```

Then open the address shown in the terminal (usually http://localhost:8501).

1. Upload a CSV file in the sidebar, or click **Use the sample dataset**.
2. Check the file summary, the column types, and the first five rows.
3. Ask a question in the box at the bottom, or click a suggested question.

---

## API

The project also provides a FastAPI API for uploading CSV files and asking questions about the uploaded data.

### Run the API

From the project folder, run:

```bash
uvicorn api:app --reload


---


## Data

The sample file `data/amazon_sales_sample.csv` holds the first 2,000 rows of
the [Amazon Sales Dataset](https://www.kaggle.com/datasets/aliiihussain/amazon-sales-dataset?resource=download) on Kaggle (a free account is needed
to download it). The orders are invented and hold no personal data. It has
13 columns, including `order_date`, `product_category`, `customer_region`,
`payment_method`, `rating` and `total_revenue`.

To try the full file (50,000 rows), download it from Kaggle and upload it
with the file uploader in the sidebar, like any other CSV. It is not in the repository because of its size.

Any other CSV file works too, as long as it uses commas between columns,
has a header row with unique column names and at least 30 rows, and is not mostly empty or duplicated. A file that fails a check is rejected with a message that says why.

---

## Example usage

| Question | What the app does |
|---|---|
| How many orders are there? | A count |
| How many orders were paid with UPI? | A count with a filter |
| What is the average rating for Electronics? | An average with a filter |
| Total revenue by region | A table and a bar chart |
| Top 3 categories by total revenue | A ranked table and a bar chart |
| Revenue by quarter | A table and a line chart |
| Show the 5 most recent orders from Europe | Matching rows, and a download of all matches |
| Which category is the best? | Asks what "best" should measure |
| Total revenue by city | Says there is no city column and lists the columns |
| Export the full table to CSV | Refused: out of scope |


Screenshots are in `screenshots/`: `input_preview.png`,
`answer_with_chart.png`, `answer_and_clarification.png`,
`error_missing_column.png`.

---

## Architecture

```
question
   │
   ▼
CLASSIFY ─────── is the request allowed? one question or several?
   │
   ▼
MAP ──────────── which column does each word mean? stop when unclear
   │
   ▼
CHOOSE TOOL ──── the model picks one of six tools and fills in its arguments
   │
   ▼
CHECK ────────── the code checks every argument before anything runs
   │
   ▼
RUN ──────────── the fixed pandas operation
   │
   ▼
ANSWER ───────── sentence + filters + table + chart
```

Each step can stop the request with a message: "Not allowed", a question to the user, or "Cannot answer" with the reason.

| Tool | Example |
|---|---|
| `count_rows` | How many orders were paid with UPI? |
| `aggregate` | Average rating for Electronics |
| `group` | Total revenue by region |
| `top_n` | Top 3 categories by revenue |
| `distinct` | Which payment methods are there? |
| `show_rows` | The 5 most recent orders from Europe |

The next step is chosen by code from the state (classify → analyse →
answer → finish), never by the model.


---


## The model

The app uses **Qwen** (`qwen/qwen3.6-35b-a3b:free`) through the xKiro API,
which follows the OpenAI API format. The model and the service address are
set in `agent/config.py`, and every call goes through one function,
`ask_llm` in `agent/llm.py`, so the model can be swapped without touching
any other part.

**Calls per question.** Each question makes up to four calls, one per step:

| Step | What the model is asked | What it returns |
|---|---|---|
| Classify | Is the request allowed? Is it one question or several? | JSON: the parts, allowed or not, with a reason |
| Map | Which column does each word of the question mean? | JSON: a column for each word, other possible columns, and how sure it is |
| Choose tool | Which of the six tools answers the question, with which arguments? | JSON: the tool and its arguments |
| Sentence | Describe this result in one or two sentences | Plain text |

For `show_rows` and for a grouping too long to show, the sentence is written
by the code, so the model is called three times.

**Settings.** `temperature=0`, so the same question gives the same answer as
far as possible, and the JSON stays in a stable shape. Each step has a limit
on the length of the reply.

**What the model sees.** The question, the column names and types, the
values of text columns with 20 or fewer distinct values, and the result for
the sentence (at most 50 rows). It never sees the raw rows of the file.

**When the reply is broken.** Every reply is read as JSON and checked in
code. A reply that cannot be read stops the request with "Something went
wrong... Please try again", instead of guessing what the model meant.

**When the service fails.** The OpenAI library retries a failed call twice
on its own. If it still fails, the user sees "The model service is
unavailable. Please try again." with a **Try again** button that sends the
same question again.

---

## Safety model

Nothing about safety is left to the model.

- **Classification.** Every request is judged before analysis. Changing the data, exporting the whole file,
  or running commands is refused. Known out-of-scope phrases ("export the", "delete all") are refused by the code
  even if the model allowed them.
- **Column mapping.** Every column the model names is checked against the
  real file. A word that could mean several columns, or no column, stops the
  request with a question to the user.
- **Closed tools.** The model can only choose one of six tools. There is no
  `exec`, `eval` or `subprocess` anywhere in the project.
- **Argument checks.** Every argument is checked in code: the measure must
  come from the user's words, IDs can only be counted, filter values must
  exist in the column or have the right type.
- **Dropped words.** If the user mentions a text or date column and the tool
  call does not use it, the user is asked instead of getting a silently
  wrong number.
- **Raw rows never reach the model.** For `show_rows`, the sentence is
  written by the code.

---

## Configuration

The limits are in `agent/config.py`:

| Setting | Value | Meaning |
|---|---|---|
| `MIN_FILE_ROWS` | 30 | smaller files are rejected |
| `MAX_SUMMARY_ROWS` | 50 | most groups or values shown in the chat; a longer grouping is offered as a download |
| `MAX_ROWS_SHOWN` | 20 | most rows `show_rows` shows |
| `WARN_EMPTY_COLUMN_SHARE` | 0.2 | a column this empty gets a warning |
| `WARN_DUPLICATE_ROWS_SHARE` | 0.05 | this share of repeated rows gets a warning |
| `REJECT_EMPTY_CELLS_SHARE` | 0.5 | a file this empty overall is rejected |
| `REJECT_DUPLICATE_ROWS_SHARE` | 0.5 | a file this repeated is rejected |
| `MAX_DOWNLOAD_SHARE` | 0.5 | matching rows can be downloaded only below this share of the file |
| `MAX_AGENT_STEPS` | 10 | safety limit on the state machine |

Warnings start early so the user knows before trusting an answer,
rejection is kept for clearly broken files.

---

## Project structure

```
ai-data-analyst/
├── app.py                    Streamlit page: shows things, decides nothing
├── .streamlit/
│   └── secrets.toml.example  copy to secrets.toml and add the API key
├── agent/
│   ├── config.py             settings and limits
│   ├── data.py               loading and checking the CSV
│   ├── llm.py                the only place that talks to the model
│   ├── prompts.py            the prompts
│   ├── classify.py           is the request allowed?
│   ├── mapping.py            which column does each word mean?
│   ├── analysis.py           get the tool call, check it, run it
│   ├── tool_call_checks.py   the checks on every argument
│   ├── tools.py              the fixed pandas operations
│   ├── agent.py              the state machine: which step is next
│   ├── state.py              the fields of one request
│   ├── errors.py             the two kinds of stop
│   └── utils.py              small helpers
├── tests/
│   ├── test_offline.py       pytest, no model
│   └── test_cases.py         full questions with the model
├── data/amazon_sales_sample.csv
├── screenshots/
├── PROJECT_PLAN.md
├── TEST_RESULTS.md
└── requirements.txt
```

Split by responsibility rather than kept as one file, so a check can be read
and tested without the loop around it.

---

## Tests

There are three kinds of tests.

**1. Without the model** (`tests/test_offline.py`, pytest). Each part is
tested on its own, with hand written inputs: loading and checking the CSV,
and each of the six tools. Tool results are compared with pandas. Runs in
about a second:

```bash
pytest tests/test_offline.py
```

**2. With the model** (`tests/test_cases.py`). Full questions go through the
whole agent: the five planned questions are printed next to their pandas
answers, and 11 more questions are checked for how they end (answer,
clarification, or refusal). Takes a few minutes:

```bash
python -m tests.test_cases
```

**3. In the app, by hand** (T1 to T10). The required test types: normal
input, missing input, an unclear question, a boundary case, an invalid file,
plus the upload preview and the chart.

| Tests | Where | Result |
|---|---|---|
| File checks and tools, without the model | `tests/test_offline.py` | 51 / 51 |
| Five planned questions, compared with pandas | `tests/test_cases.py` | 5 / 5, exact match |
| Other questions (clarification, refusal, fixed errors) | `tests/test_cases.py` | 11 / 11 |
| Required tests T1 to T10 | in the app | 10 / 10 |

All results, and the errors found and fixed during testing, are in
`TEST_RESULTS.md`.


## New tools learned

**Streamlit**:
`file_uploader` (CSV upload), `chat_input` and `chat_message` (the question
box and the conversation), `session_state` (the file, the history and the
question being answered, kept across reruns and cleared on a new file),
`st.status` (progress steps while the agent works),
`st.container(height=...)` (a conversation box that scrolls on its own),
`st.download_button` (downloading results and matching rows), `st.secrets`
(the API key), `st.columns` (suggested questions side by side) and
`st.expander` (the first five rows, and "How the agent decided").

**Plotly.** Bar and line charts built from the result table, with the chart
type chosen from the data (a line for months, bars for categories) and
labelled axes. Because the chart is drawn from the same table, it always
agrees with it.

**pytest.** Tests as small functions with `assert`, one test over many cases
with `parametrize`, the data loaded once with a `fixture`, and expected
errors checked with `pytest.raises`.

---

## Known limitations

- **One question at a time.** A request with two questions is sent back with
  a request to split it.
- **No calculations across columns** (for example revenue minus cost), **no
  averages of totals** (for example the average monthly revenue), and **no
  statistics** such as correlation or forecasting.
- **Size limits:** at most 2 grouping columns. A grouping with more than 50
  groups is offered as a download instead of a table, A grouping with close
  to one group per row is refused, because that would be the file itself.
  `show_rows` shows at most 20 rows, and all matching rows can be downloaded
  only when they are less than half of the file.
- **Commas only.** A file that uses semicolons is rejected with a message,
  because such files often also use a decimal comma ("12,50"), which would
  turn numbers into text.
- **What is sent to the external model:** the question, column names and
  types, the values of text columns with 20 or fewer distinct values, and
  the aggregated result (at most 50 rows) for the sentence. Raw rows are
  never sent.
- **The model interprets words.** "Gadgets" is read as Electronics, the
  answer names the category it used and the filter is shown, so the user can
  see the interpretation.
- **Speed:** each question makes three or four calls to the model service,
  so an answer takes about 15 seconds.
- **Language:** questions in Arabic also worked in a quick try (for example,
  the average rating per payment method), but they were not part of the
  tests, so English is the supported language.
- **Some clarification messages are unclear.** For a value that does not
  exist ("average rating for Toys"), the app asks instead of answering, but
  the message may name the column rather than the word the user wrote.

---

## Author
**Dema Jamal Abukwaik**