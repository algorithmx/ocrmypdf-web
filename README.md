ocrmypdf-web
===

## Introduction

This is a containerized solution of `ocrmypdf` program. I have added image proprocessing to enhance the OCR results.

## Run

You need docker engine to run this project.

- First, build the project
    `docker compose build`

- Then run the following to start service:
    `docker compose up`

## Note

I live in a country where internet access is completely free without any restrictions, that is well-known to everybody live inside and outside that country. I will ignore any disagreements on this fact.

If you don't live in this country, you may remove the mirror option in the `Dockerfile`, i.e. change

`RUN pip3 install -i https://mirrors.sustech.edu.cn/pypi/web/simple/ --no-cache-dir -r requirements.txt`

to 

`RUN pip3 install --no-cache-dir -r requirements.txt`
