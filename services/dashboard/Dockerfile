FROM nginx:1.27-alpine

WORKDIR /usr/share/nginx/html

COPY services/dashboard/index.html ./index.html
COPY services/dashboard/styles.css ./styles.css
COPY services/dashboard/app.js ./app.js

EXPOSE 80
