---
title: Overview
nav_order: 1
---

# Overview

Evaluating Elasticsearch storage architectures for open source repository activity at scale

---

## Summary

In 2024, a Harvard Business School study estimated the value of widely used open source software (OSS) at $8.8 trillion. OSS sits inside virtually every modern codebase, and when it fails, everything built on it is at risk. In fact, the 2024 XZ Utils backdoor showed how close that came to happening.

With so much at stake, researchers in Mining Software Repositories and initiatives such as CHAOSS (Community Health Analytics in Open Source Software) analyse large volumes of OSS activity data from platforms like GitHub. Their findings help maintainers grow stronger communities, and help the companies and funders that rely on OSS know where support is needed most.

The first step in that research is collecting the data, whether through APIs, existing datasets or by hand. That alone is a challenge. Once you have it, another question follows: how should you store it? The answer affects query speed, processing time, maintenance effort and hardware costs.

Now, imagine you want to open a new library. Suppose you already have a source supplying you with thousands of books, but you need a way to organise them, and there's no guide for a library quite like this one. Do you sort them onto shelves, group them by genre, securely lock some away, or remove any damaged ones first? If people are going to find anything, the design matters. However, before that, you need a suitable building.

Elasticsearch (ES) fits the bill for text-based activity data (issues, pull requests, comments and reviews). It's a distributed search and analytics engine that returns results fast, scales horizontally as data grows, and comes with tools for indexing, lifecycle management and visualisation.

Great, so we have ES, but should we just store the data as-is? Technically we could, but that would be like leaving all the books boxed up inside the front door. What we need is a floor plan, and every layout comes with its own cost.

This honours thesis studies exactly that. Using public GitHub activity from GH Archive, it stores the same data in several layouts and configurations, then compares them on storage, loading speed, query speed and computing resources.

The expected outcome is an evidence-based set of recommendations, a reference architecture. A floor plan for your library. No single plan suits every library, but this one aims to make the trade-offs clear and point you in the right direction.
