"""識別の中核。HTTP 層 (main.py) と精度評価 (eval/) の両方がここを通る。

評価スクリプトが独自に手順を組み立てると、測っている経路が本番と静かにずれる。
プロバイダーの選択、Pl@ntNet の併用、証拠ゲートの適用順はこの1か所に置く。
"""

from typing import Any

import vision


def identify_all(
    prepared: list[bytes],
    *,
    provider: str,
    model: str,
    api_key: str = "",
    ollama_url: str = vision.OLLAMA_URL,
    location: str = "",
    observed_date: str = "",
    size: str = "",
    use_plantnet: bool = False,
    plantnet_key: str = "",
) -> dict[str, Any]:
    """前処理済み画像から識別結果を返す。証拠ゲートまで適用した最終形。"""
    context = {"location": location, "observed_date": observed_date, "size": size}
    if provider == "openai":
        result = vision.identify_openai(prepared, api_key, model, **context)
    elif provider == "anthropic":
        result = vision.identify_anthropic(prepared, api_key, model, **context)
    elif provider == "gemini":
        result = vision.identify_gemini(prepared, api_key, model, **context)
    else:
        result = vision.identify(prepared, model, ollama_url=ollama_url, **context)

    if use_plantnet:
        if not plantnet_key:
            result["plantnet_status"] = "not_configured"
        # 植物と判定したときだけ呼ぶ。Pl@ntNet の結果は VLM の候補を置き換えるので、
        # 植物でない写真に投げると丸ごと誤答になる。実測では菌類6枚がすべて植物名に
        # すり替わった (シロソウメンタケ → Pachysandra procumbens など)。
        elif result.get("category") != "植物":
            result["plantnet_status"] = "not_plant"
        else:
            try:
                specialist = vision.identify_plantnet(prepared, plantnet_key)
                result = vision.merge_plant_results(result, specialist)
            except vision.VisionError as plantnet_error:
                result["plantnet_status"] = "unavailable"
                result["plantnet_message"] = str(plantnet_error)

    return vision.apply_evidence_gate(result)
