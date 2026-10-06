# 日本城郭検定3級 校閲から販売まで

## 利用者への共有
紹介：/products/shiro-3
無料体験：/products/shiro-3/trial
資料一覧：/products/shiro-3/materials
固定された7種類の資料だけを閲覧・保存できます。既存exam-trainerのアクセス範囲は変更しません。
noindexは認証機能ではありません。全問PDFはアプリに到達できる利用者が保存できます。

## 校閲
review-20e459f7c307.csvに全問の確認結果・校閲者・修正内容を記録します。
出典本文、正誤、選択肢、検定の出題範囲・難易度、出典の利用条件を人が確認します。
本教材は公開資料を参照した独自作成の練習問題です。学習履歴を変更せず、更新は教材JSONに反映します。

## 更新と再構築
src/exam_trainer/products/shiro-3.jsonがこの版の教材データです。
`~/.venv/bin/python app/exam-trainer/scripts/build_products.py`でPDF・原稿を再構築します。
内容変更後はSHAが変わり、販売の承認は失効します。CSVは版ごとに作り、既存の校閲記録を上書きしません。
販売説明の手修正も上書きしません。問題数や説明の変更時は販売原稿を合わせて確認します。
artifact-state.jsonは教材SHAと各資料のファイルSHAを記録します。旧版・手修正後の未確認資料は更新待ちとなり配信を止めます。
販売原稿が現在の版に合うことを確認したら、再構築に--confirm-sales-copyを付けて記録します。
この確認は販売原稿の版の照合であり、問題の校閲・販売の承認ではありません。

## 販売
全問の校閲と出典条件の確認後、shiro-3-release.jsonにreviewed_sha256、reviewer、reviewed_atを記録します。
source_terms_checkedをtrueにし、BOOTHへの出品後にhttpsのBOOTH商品URLをbooth_urlに設定します。
価格は未定です。価格を教材JSONに設定した場合も、変更後のSHAに対して承認します。
承認のSHAが現在の教材と一致し、条件確認済みで有効な商品URLがあるときだけ購入リンクが表示されます。
PDFを再構築し、保存版の表示・版・全問数を確認してから販売します。
