"""Q1 to Q7, one module per query.

Each module provides:

    reference(data, repo_id) -> answer
        The answer computed in Python from the records: the yardstick.
    informative(answer) -> bool
        Whether the answer is non-trivial enough to benchmark a repository on.
    s1(es, tier, repo_id) ... s4(es, tier, repo_id) -> (answer, requests)
        The same answer from one layout, and the number of requests it took.

Every layout must return exactly the reference answer.
"""
