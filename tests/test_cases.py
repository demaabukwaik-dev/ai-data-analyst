from agent.agent import run_agent
from agent.config import SAMPLE_DATA_PATH
from agent.data import load_csv

df, _ = load_csv(SAMPLE_DATA_PATH)


def how_it_ended(state):
    if state["answered"]:
        return "answer"
    if state["authorized"] is False:
        return "reject"
    if state["stop_type"] == "NeedsClarification":
        return "clarify"
    return "cannot"


# the five planned questions: agent answer next to pandas

state = run_agent("How many orders are there?", df)
print("Count     agent:", state["result"], "  pandas:", len(df))

state = run_agent("How many orders were paid with UPI?", df)
print("UPI       agent:", state["result"], "  pandas:", (df["payment_method"] == "UPI").sum())

state = run_agent("What is the average rating for Electronics?", df)
electronics = df[df["product_category"] == "Electronics"]
print("Rating    agent:", round(state["result"], 2), "  pandas:", round(electronics["rating"].mean(), 2))

state = run_agent("Total revenue by region", df)
print("\nRevenue by region, agent:")
print(state["result"])
print("pandas:")
print(df.groupby("customer_region")["total_revenue"].sum().round(2))

state = run_agent("Top 3 categories by total revenue", df)
print("\nTop 3 categories, agent:")
print(state["result"])
print("pandas:")
print(df.groupby("product_category")["total_revenue"].sum().nlargest(3).round(2))


# other questions: how each one should end

tests = [
    ("Which category is the best?", "clarify"),
    ("Which region performs worst?", "clarify"),
    ("Revenue by week of year", "answer"),
    ("Export the full table to CSV", "reject"),
    ("Total revenue by city", "clarify"),
    ("Total revenue in 2030", "cannot"),
    ("Total revenue and number of orders", "clarify"),
    ("What is the average rating for gadgets?", "answer"),
    ("What is the average monthly total revenue?", "cannot"),
    ("Average revenue by month", "answer"),
    ("Show the 5 most recent orders from Europe", "answer"),
]

print()
for question, expected in tests:
    state = run_agent(question, df)
    got = how_it_ended(state)
    if got == expected:
        print("ok   ", question)
    else:
        print("FAIL ", question, "- expected", expected, "but got", got)
        print("      ", state["answer_text"] or state["rejection_reason"])