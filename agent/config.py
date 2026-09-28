
API_MODEL = "qwen/qwen3.6-35b-a3b:free"
API_BASE = "https://api.xkiro.com/v1"

SAMPLE_DATA_PATH = "data/amazon_sales_sample.csv"  # sample dataset used by the app and the tests


MIN_FILE_ROWS = 30                 # smaller files are rejected
MAX_SUMMARY_ROWS = 50              # max groups or values shown in the chat, a longer grouping is offered as a download
MAX_ROWS_SHOWN = 20                # show_rows never returns more than this
MAX_AGENT_STEPS = 10               # safety limit on the loop

WARN_EMPTY_COLUMN_SHARE = 0.2      # a column this empty gets a warning
WARN_DUPLICATE_ROWS_SHARE = 0.05   # this share of repeated rows gets a warning

REJECT_EMPTY_CELLS_SHARE = 0.5     # a file this empty overall is rejected
REJECT_DUPLICATE_ROWS_SHARE = 0.5  # a file this repeated is rejected

MAX_DOWNLOAD_SHARE = 0.5           # a download (matching rows or groups) must be smaller than this share of the file

PRINT_MODEL_REPLIES = False        # True prints the model's raw replies to the terminal