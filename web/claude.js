// «Умный» режим: при наличии сети и ключа вопросы, которые не распознал
// локальный мозг, уходят в Claude с веб-поиском.
const SDK_URL = 'https://cdn.jsdelivr.net/npm/@anthropic-ai/sdk@0.131.0/+esm';
const MODEL = 'claude-opus-5-5';
// Начинаем новый разговор, а не обрезаем старый: история должна только дописываться.
const MAX_MESSAGES = 40;

let sdk = null;
let convo = null; // { system, messages }

async function loadSdk() {
  sdk ??= (await import(SDK_URL)).default;
  return sdk;
}

function buildSystem(data) {
  const facts = data.memory.map((x) => `- ${x.text}`).join('\n') || '- (пока пусто)';
  const tasks = data.tasks.filter((x) => !x.done).map((x) => `- ${x.text}`).join('\n') || '- (нет)';
  return `Ты — Искра, персональный голосовой ИИ-помощник пользователя на его телефоне Samsung Galaxy.
Обращайся к пользователю «${data.settings.name || 'дружище'}», на «ты», тепло и по-дружески.
Отвечай по-русски, коротко и по делу: ответ будет зачитан вслух, поэтому избегай таблиц, markdown и длинных списков.
Если нужны свежие данные (новости, курсы, погода, цены), пользуйся веб-поиском.
Ты не выполняешь действия на телефоне сама: если пользователь хочет позвонить, написать СМС или поставить напоминание,
подскажи ему точную команду, например «Позвони 8999…» или «Напомни через 10 минут …».
Помогай с заработком и проектами честно: без схем быстрого обогащения, с реальными шагами.

Что ты помнишь о пользователе:
${facts}

Его открытые задачи:
${tasks}`;
}

function textOf(content) {
  return content.filter((b) => b.type === 'text').map((b) => b.text).join('').trim();
}

/** Сбрасывает разговор, чтобы следующий вопрос начался с актуальной памятью. */
export function resetConversation() {
  convo = null;
}

export async function askClaude(question, data) {
  const Anthropic = await loadSdk();
  const client = new Anthropic({ apiKey: data.settings.apiKey, dangerouslyAllowBrowser: true });

  if (!convo || convo.messages.length >= MAX_MESSAGES) {
    convo = { system: buildSystem(data), messages: [] };
  }
  convo.messages.push({ role: 'user', content: question });

  try {
    // Веб-поиск может поставить ход на паузу (pause_turn) — продолжаем до 3 раз.
    for (let i = 0; i < 4; i++) {
      const response = await client.beta.messages.create({
        model: MODEL,
        max_tokens: 4096,
        betas: ['server-side-fallback-2026-07-01'],
        fallbacks: 'default',
        output_config: { effort: 'low' },
        system: convo.system,
        tools: [{ type: 'web_search_20260209', name: 'web_search', max_uses: 3 }],
        messages: convo.messages,
      });

      if (response.stop_reason === 'refusal') {
        convo.messages.pop();
        return 'С этим вопросом я помочь не смогу. Давай попробуем что-нибудь другое.';
      }
      convo.messages.push({ role: 'assistant', content: response.content });
      if (response.stop_reason !== 'pause_turn') {
        return textOf(response.content) || 'Готово.';
      }
    }
    return 'Поиск занял слишком много шагов. Попробуй спросить точнее.';
  } catch (err) {
    // Неудачный ход не должен оставаться в истории.
    convo = null;
    if (err instanceof Anthropic.AuthenticationError) return 'Ключ Claude не подошёл. Проверь его в настройках.';
    if (err instanceof Anthropic.RateLimitError) return 'Слишком много запросов. Подожди минутку и спроси снова.';
    if (err instanceof Anthropic.APIConnectionError) return 'Не получилось связаться с Claude — похоже, пропала сеть.';
    if (err instanceof Anthropic.APIError) return `Claude ответил ошибкой (${err.status ?? '?'}). Попробуй позже.`;
    throw err;
  }
}
