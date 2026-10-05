# publish.py build が書き出した静的サイトを配るだけ。生成キューも保存DBも入れない。
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY site/ /usr/share/nginx/html/
