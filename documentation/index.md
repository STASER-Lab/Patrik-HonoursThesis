---
title: Overview
nav_order: 1
---

# Overview

In 2024, a Harvard Business School study estimated the value of widely used open source software (OSS) at $8.8 trillion. Today, OSS underpins virtually every modern codebase, making its reliability and security critical to the systems built on it. The 2024 XZ Utils backdoor incident demonstrated just how far-reaching the consequences of a single compromise could be.

Given the scale and importance of OSS, researchers in Mining Software Repositories (MSR) and initiatives such as CHAOSS analyse vast amounts of activity data from platforms like GitHub. Their findings help maintainers build healthier communities while giving the companies and funders that depend on OSS a better understanding of where support and resources are needed most.

This research begins with collecting data, whether through APIs, existing datasets, or other sources. But collecting the data is only the first challenge. Once obtained, it must also be stored and organised in a way that supports efficient analysis. These decisions have a direct impact on query performance, processing time, maintenance effort, and infrastructure costs.

Consider a new library with thousands of books but no established system for organising them. Should they be arranged by genre, author, or popularity? Should some be kept in secure storage, or should damaged books be removed altogether? Each decision affects how easily readers can find what they need and how efficiently the library operates. Before the collection can be organised, however, it needs a suitable place to be stored.

Elasticsearch (ES) provides such a foundation for text-based software repository activity, including issues, pull requests, comments, and reviews. As a distributed search and analytics engine, it offers fast retrieval, horizontal scalability, and tools for indexing, lifecycle management, and visualisation. However, choosing a storage platform is only part of the problem. How the data is organised within it can have just as much impact on performance and resource requirements.

This is the problem addressed by this honours thesis. Using public GitHub activity data from GH Archive, the research project implements several document layouts and configurations in Elasticsearch. These alternatives are evaluated and compared across storage requirements, data loading time, query performance, and computational resource consumption.

The expected outcome is an evidence-based set of recommendations for designing Elasticsearch document layouts for software repository activity. Since no single configuration is optimal for every use case, the goal is to clarify the trade-offs between different approaches and provide practical guidance for making informed design decisions.
