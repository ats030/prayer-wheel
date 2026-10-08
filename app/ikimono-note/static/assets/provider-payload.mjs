// The server supplies prompts/settings through vision.provider_payload(..., []).
// This builds bytes only. It does not authorize forwarding or select an API URL.
export function assembleProviderPayload(provider, template, images) {
  if (!Array.isArray(images) || images.length < 1 || images.length > 3 ||
      images.some(image => typeof image !== 'string' || !image.length)) {
    throw new TypeError('写真は1〜3枚選んでください');
  }
  const payload = structuredClone(template);
  if (provider === 'openai') {
    const content = payload.input?.[0]?.content;
    if (payload.input?.length !== 1 || content?.length !== 1 || content[0].type !== 'input_text') {
      throw new TypeError('Invalid provider template');
    }
    payload.input[0].content = [
      ...images.map(image => ({type: 'input_image', image_url: 'data:image/jpeg;base64,' + image})),
      ...content,
    ];
  } else if (provider === 'anthropic') {
    const content = payload.messages?.[0]?.content;
    if (payload.messages?.length !== 1 || content?.length !== 1 || content[0].type !== 'text') {
      throw new TypeError('Invalid provider template');
    }
    payload.messages[0].content = [
      ...images.map(image => ({type: 'image', source: {type: 'base64', media_type: 'image/jpeg', data: image}})),
      ...content,
    ];
  } else if (provider === 'gemini') {
    const parts = payload.contents?.[0]?.parts;
    if (payload.contents?.length !== 1 || parts?.length !== 1 || typeof parts[0].text !== 'string') {
      throw new TypeError('Invalid provider template');
    }
    payload.contents[0].parts = [
      ...images.map(image => ({inline_data: {mime_type: 'image/jpeg', data: image}})),
      ...parts,
    ];
  } else {
    throw new TypeError('使うAIを選び直してください');
  }
  return payload;
}
