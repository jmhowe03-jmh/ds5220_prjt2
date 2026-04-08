# DS5220 Data Project 2: WEATHER TRACKER 
## vxx4kn Jillian Howe
Create, schedule, and run a containerized data pipeline in Kubernetes.

## Overview

In this project you will design, containerize, schedule, and operate a real data pipeline running inside a Kubernetes host on AWS. A working sample application is provided that tracks the International Space Station every 15 minutes, records its position and altitude in DynamoDB, and detects orbital burns when the altitude is raised significantly. You will study how that pipeline works, then build your own data application that collects data on a schedule, persists it, and publishes an evolving plot to a public S3 website.

Your pipeline should run for at least 72 hours, collecting at least 72 data points. Choose a data source that is updated at least hourly.

### Learning Objectives

By the end of this project you will be able to wrangle all the elements of a working container-driven data pipeline:

1. **Provision cloud infrastructure** — launch and configure an EC2 instance, attach an Elastic IP and proper IAM role/policy, and enable S3 static website hosting.
2. **Deploy and operate Kubernetes** — install K3S, inspect cluster state with `kubectl`, and understand namespaces, pods, secrets, and jobs.
3. **Containerize a Python application** — write a Python application, `Dockerfile`, build a container image, and push it to a public container registry (GHCR).
4. **Schedule work with CronJobs** — define a Kubernetes `CronJob` manifest, control its schedule, and retrieve logs from completed job pods.
5. **Manage secrets securely** (optional) — store API keys as Kubernetes Secrets and inject them as environment variables so sensitive values never appear in code or YAML files.
6. **Persist data in DynamoDB** — create a DynamoDB table with a partition key and sort key, write items from a containerized job, and query for the most recent entry.
7. **Consume a REST API programmatically** — parse JSON responses and handle incremental data collection across repeated runs.
8. **Generate and publish data visualizations** — produce an evolving time-series plot with `seaborn`, overwrite it on each pipeline run, and serve it via S3 website hosting.

---
- **Open-Meteo Weather API** — fetch hourly temperature, wind speed, precipitation, or cloud cover for any lat/lon without an API key. [https://open-meteo.com/en/docs](https://open-meteo.com/en/docs)

## Deliverables

Submit the following in the Canvas assignment:

1. **Your Data Application Plot URL** — [the public `http://` URL to your `plot.png` served from your S3 website bucket (e.g., `http://your-bucket-name.s3-website-us-east-1.amazonaws.com/plot.png`). The plot must represent at least 72 hours / 72 entries of data. Paste the URL directly — if the image does not load it will not be graded.](https://vxx4kn-weather-bucket.s3.us-east-1.amazonaws.com/weather/syracuse_ny-weather.png)


3. **Your Data Application Repo URL** — [the public GitHub URL to your pipeline code. The repository must include the Python script, a `Dockerfile`, and a `requirements.txt`.](https://github.com/jmhowe03-jmh/ds5220_prjt2)

4. **Canvas Quiz** — answer the short-answer questions posted in Canvas. These will ask you to reflect on what you built, including:
    - Which data source you chose and why.
    - What you observe in the data — any patterns, spikes, or surprises over the 72-hour window.
    - How Kubernetes Secrets differ from plain environment variables and why that distinction matters.
    - How your CronJob pods gain permission to read/write to AWS services without credentials appearing in any file.
    - One thing you would do differently if you were building this pipeline for a real production system.

### Graduate Students

1. In the ISS sample application, data is persisted in DynamoDB. If this were a much higher-frequency application (hundreds of writes per minute), what changes would you make to the persistence strategy and why?
   A higher frequency application could overwhelm AWS and the supporting functions. I would batch or collect multiple entries every 1 minute or so in order to combat this.
3. The ISS tracker detects orbital burns by comparing consecutive altitude readings. Describe at least one way this detection logic could produce a false positive, and how you would make it more robust.
    If the data is noisy or inaccurate or pulls it from a strange place in its orbit it may produce a false positive. Additionally, the orbit is elliptical, I would assume, and I am not sure if the units for altitude are consistent throughout the ellipse, and this change in location along the curve may appear lower/higher as a result.
4. How does each `CronJob` pod get AWS permissions without credentials being passed into the container?
   The cronjob is launched from inside the ubuntu terminal so there is no need for credentials to be passed to the AWS in order to commincate
5. Notice the structure of the `iss-tracking` table in DynamoDB. What is the partition key and what is the sort key? Why do these work well in this example, but may not work for other solutions?
   The partition key is the satellite ID, and the sort key is the timestamp. This is effective in this case, as it would be easy to tell Dynamo to pull the records from the past day, and as it can easily pull this data and they are both stored sequentially, which is pivotal in this project. This might not work if we are tracking more than one thing in the same dynamo table or workspace. 
