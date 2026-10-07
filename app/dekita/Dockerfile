FROM nginx:alpine

COPY index.html /usr/share/nginx/html/
COPY style.css /usr/share/nginx/html/
COPY favicon.svg /usr/share/nginx/html/
COPY migration.html migration.js /usr/share/nginx/html/
COPY src /usr/share/nginx/html/src/
COPY audio /usr/share/nginx/html/audio/

RUN rm /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
