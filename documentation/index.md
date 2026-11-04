---
title: Overview
nav_order: 1
---

# Overview

Evaluating Elasticsearch storage architectures for open source repository activity at scale

---

## Summary

In 2024, a Harvard Business School study estimated the value of widely used open source software (OSS) at $8.8 trillion. OSS sits inside virtually every modern codebase, and when it fails, everything built on it is at risk. In fact, the 2024 XZ Utils backdoor showed how close that came to happening.

With so much at stake, researchers in Mining Software Repositories and initiatives such as CHAOSS (Community Health Analytics in Open Source Software) analyse large volumes of OSS activity data from platforms like GitHub. Their findings help maintainers grow stronger communities and help the companies and funders that rely on OSS understand where support is needed most.

The first step in this research is collecting data, whether through APIs, existing datasets, or manual collection. That alone is a challenge. Once you have it, another question follows: how should you store it? The answer affects query speed, processing time, maintenance effort, and hardware costs.

Now, imagine you want to open a new library. Suppose you already have a source that provides thousands of books, but you need a way to organise them, and there's no existing guide for a library quite like yours. Do you sort them onto shelves, group them by genre, securely lock some away, or remove damaged ones first? If people are going to find anything, the design matters. However, before that, you need a suitable building.

Elasticsearch (ES) fits the bill for text-based activity data (issues, pull requests, comments, and reviews). It's a distributed search and analytics engine that returns results fast, scales horizontally as data grows, and comes with tools for indexing, lifecycle management, and visualisation. So, we have Elasticsearch. But simply having a place to store our data doesn't mean we've figured out how best to organise it.

This honours thesis studies exactly that. Using public GitHub activity from GH Archive, it stores the same data in several layouts and configurations, then compares them on storage, loading speed, query speed, and computing resources.

The expected outcome is an evidence-based set of recommendations. No single design suits every need, but these recommendations aim to clarify the trade-offs and help guide design decisions.
