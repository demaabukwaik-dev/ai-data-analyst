# TEST_RESULTS: AI Data Analyst

- Tests with the model were run in the app on the sample dataset
(`data/amazon_sales_sample.csv`, 2,000 rows).

- Tests without the model run with
`pytest tests/test_offline.py` (51 tests, all passing).

---

## 1. Required tests

| ID | Type | Input / situation | Expected behaviour | Actual behaviour | Pass / Fail |
|---|---|---|---|---|---|
| T1 | Normal valid input | "Total revenue by region" | Table and bar chart, values equal a pandas `groupby().sum()` | Table of 4 regions and a bar chart, North America highest (352,831.11), Europe lowest (292,284.50) |  Pass |
| T2 | Required field missing | No file uploaded | "Upload a CSV file in the sidebar to start." | Same message, no preview and no answers shown |  Pass |
| T3 | Ambiguous / incomplete request | "Which category is the best?" | Asks what to measure and lists the choices, no number is shown | "What do you want to measure? Please choose one: ... " |  Pass |
| T4 | Boundary or unsupported request | "Revenue by week of year" (52 weeks) | Too many groups to show (limit 50): the grouping is offered as a download | "This grouping gives 52 groups, too many to show here (limit 50). You can download them all below, or ask for a higher level grouping or the top groups." and a "Download all 52 groups" button | Pass |
| T5 | Invalid file / tool error | Upload an empty CSV | "The file is empty.", nothing else runs | Same message |  Pass |
| T6 | Out of scope | "Export the full table to CSV" | "Not allowed" with the reason | "Not allowed: Exporting or downloading the whole table is out of scope." |  Pass |
| T7 | Missing column | "Total revenue by city" | Says the column does not exist and lists the available columns | "'city' has no usable column. Available columns: ..." |  Pass |
| T8 | No matching rows | "Total revenue in 2030" | "No records match the filters (...)" | "No records match the filters (order_date (year) == 2030)." |  Pass |
| T9 | Valid CSV upload | Load the sample dataset | Row and column counts, column names and types, and the first five rows match pandas | 2,000 rows and 13 columns, types shown: 2 ID, 1 date, 3 text, 7 number. the first five rows equal `df.head(5)` |  Pass |
| T10 | Chart and code safety | "Total revenue by region", search the code for `exec`, `eval` | Bars equal the table, no model code runs | Bars equal the table (Asia 335,017.69), no `exec` or `eval` found |  Pass |
| T11 | Tool error (model service fails) | Ask a question with a wrong API key | An error message and a "Try again" button; no invented result | "The model service is unavailable. Please try again." and a "Try again" button; after the key was fixed, "Try again" answered the question | Pass |


---

## 2. Tests without the model

The loading checks and the tools were tested on their own, before they were
connected to the model or the interface, with hand written inputs. Tool
results are compared to a pandas calculation written by hand.

Run: `pytest tests/test_offline.py` : **51 passed**

| Group | What is tested | Tests | Result |
|---|---|---|---|
| Loading the CSV | Not a .csv, empty file, header only, repeated column names, wrong separator, fewer than 30 rows | 6 |  Pass |
| Types | Codes with leading zeros stay text ("01123"), text numbers become numbers, text dates become dates | 1 |  Pass |
| Data quality | A column 60% empty → warning (limit 20%), a file 67% empty → rejected (limit 50%), 10% duplicate rows → warning (limit 5%), 65% duplicate rows → rejected (limit 50%), the sample file → no warnings | 5 |  Pass |
| Valid tool calls | Each of the six tools, a date part (quarter, weekend), and an ID filter (order 1005) | 10 |  Pass |
| Unclear tool calls ask the user | No measure ("best"), a measure the user never mentioned, a value that does not exist, several questions at once | 5 |  Pass |
| Unsupported tool calls are refused | Unknown tool, sum of an ID, average of text, text compared with ">", a number or date written as text, a filter that matches no rows (orders from 2030), a month of 13, "Funday" | 12 |  Pass |
| Long groupings | 52 weeks are returned for download, one group per order is refused | 2 | Pass |
| Results match pandas | Top 3 categories by revenue, orders from Europe paid by UPI, total revenue in 2023, total revenue in March, `show_rows` asked for 500 rows returns 20 | 5 |  Pass |
| Model mistakes repaired or caught | A concept name replaced by its column, "month" sets the date part, a dropped filter is caught, an ignored "monthly" is caught, a counted ID is not taken for a dropped filter | 5 |  Pass |

## 3. Five planned questions (checked against pandas)

| Type | Question | Answer in the app | Independent pandas check | Pandas result | Pass / Fail |
|---|---|---|---|---|---|
| Count | How many orders are there? | 2,000 | `len(df)` | 2000 |  Pass |
| Filter | How many orders were paid with UPI? | 435 | `(df.payment_method == "UPI").sum()` | 435 |  Pass |
| Average | What is the average rating for Electronics? | 3.00 | `df[df.product_category == "Electronics"].rating.mean()` | 3.0 |  Pass |
| Grouped comparison | Total revenue by region | North America 352,831.11 (highest), Europe 292,284.50 (lowest) | `df.groupby("customer_region").total_revenue.sum()` | Asia 335,017.69; Europe 292,284.50; Middle East 311,938.02; North America 352,831.11 |  Pass |
| Top item | Top 3 categories by total revenue | Books 227,422.85, Sports 226,405.74, Fashion 225,397.99 | `df.groupby("product_category").total_revenue.sum().nlargest(3)` | Books 227,422.85; Sports 226,405.74; Fashion 225,397.99 |  Pass |

## 4. Two unclear questions

| Question | Expected clarification | Actual behaviour | Pass / Fail |
|---|---|---|---|
| Which category is the best? | Asks what to measure | "What do you want to measure? Please choose one: ..." |  Pass |
| Which region performs worst? | Asks what to measure; no number is shown | "What do you want to measure? Please choose one: price, discount_percent, quantity_sold, rating, review_count, discounted_price, total_revenue, number of records." |  Pass |

---

## 5. Failures found and fixed

Each of these failed during testing. The fix was made, and the test was run
again and passed.

### 5.1 Wrong answers that looked correct

| Question | What happened | Cause | Fix |
|---|---|---|---|
| Which category is the best? | Ranked the categories by their number of orders and called the top one "best" | The model chose a measure by itself | The measure must come from the user's words, otherwise the user is asked |
| Monthly revenue in 2023 | "No records match", as if there were no orders in 2023 | The number 2023 was read as a date in 1970 | A year became a date part (`part: "year"`) |
| Monthly revenue in 2023 (a later run) | Refused: 365 groups | The model grouped by "month" without saying it was a part of the date, so each day became a group | When the model groups by a concept named after a date part ("month"), the code adds that part (`date_part: "month"`) |
| What is the average monthly total revenue? | 657.33, which is the average per order | The model ignored "monthly" | A date column the user mentions must be used, otherwise the user is asked |
| What is the average monthly total revenue? (a later run) | A table of the average order in each month, called "average monthly total revenue" | An average of monthly totals needs two steps, no tool does this | Tool rule: an average of totals returns "none", so the user is told it is not supported, "Average revenue by month" is still answered |
| Total revenue and number of orders | Answered only one part | One tool answers one question | The user is asked to send one question at a time |
| Average price by region (a 30-row test file) | Refused: `price` was treated as an ID | Every price in the small file was different, so it looked like an ID column | Decimal columns (prices, amounts) are never treated as IDs, even when every value is different |

### 5.2 Valid questions refused or asked about for no reason

| Question | What happened | Cause | Fix |
|---|---|---|---|
| Total revenue in 2030 | "column does not exist: year" | The model wrote the word from the question instead of the column | The code replaces the word with its column from the map |
| Revenue by week of year | "Could not tell what to group by" | Same cause | Same fix |
| How many orders on weekends? | Asked what to measure | The map did not link "orders" to a column | Map rule: the thing being counted is a concept too |
| How many employees work remotely? | Asked the user to clarify instead of answering | The question mentions "employees" (linked to `employee_id`). The check for dropped filters saw that `employee_id` was not used.| The check ignores ID columns, mentioning them ("employees", "orders") means counting them, not filtering by them |
| How many rows are there? | "Could not map this question" | An empty map was treated as an error | An empty map is accepted |
| How many rows are there? (a later run) | "'row_count' has no usable column" | The model made a concept for the rows | Map rule: rows are not a concept |
| Which category is the best? | Refused as not allowed | The classifier treated an unclear question as forbidden | Classifier prompt: unclear questions are allowed, a later step asks |
| Top 5 products by revenue | Refused: more than 50 groups | The limit was applied to all the groups before taking the top 5 | `top_n` computes every group but shows only the top n, so the 50-group limit no longer blocks it  |

---

