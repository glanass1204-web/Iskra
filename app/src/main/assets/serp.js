// Достаёт ответы со страницы выдачи Яндекса или Google.
// Не опирается на конкретные классы: и там и там заголовок результата — h2/h3 внутри ссылки.
(function () {
  function clean(t) { return (t || '').replace(/\s+/g, ' ').trim(); }
  var href = location.href;
  var captcha = /showcaptcha|checkcaptcha|\/sorry\//.test(href) ||
    !!document.querySelector('#checkbox-captcha-form, .CheckboxCaptcha, form[action*="captcha"], #captcha-form, iframe[src*="recaptcha"]');
  var out = [];
  var seen = {};
  function add(title, snippet, url) {
    title = clean(title); snippet = clean(snippet);
    if (snippet.length < 25) return;
    var key = url || title;
    if (seen[key]) return;
    seen[key] = 1;
    out.push({ t: title, s: snippet.slice(0, 600), u: url || href });
  }

  // Готовые ответы: факты Яндекса, блоки ответов Google.
  var boxes = document.querySelectorAll(
    '.Fact-Answer, .FactAnswer, .FactFoldable, .EntitySearch-Description, .entity-search__description, ' +
    '.hgKElc, .Z0LcW, .IZ6rdc, [data-attrid="wa:/description"], .kno-rdesc span');
  for (var b = 0; b < boxes.length && out.length < 1; b++) add('Ответ', boxes[b].innerText, href);

  var ad = /^(реклама|sponsored|спонсор|ad\b)/i;
  var engineHost = /(^|\.)(yandex\.[a-z]+|ya\.ru|google\.[a-z.]+|gstatic\.com)$/;
  var heads = document.querySelectorAll('a h2, a h3, h2 a, h3 a');
  for (var i = 0; i < heads.length && out.length < 5; i++) {
    var node = heads[i];
    var link = node.tagName === 'A' ? node : node.closest('a');
    var heading = node.tagName === 'A' ? node.closest('h2, h3') : node;
    if (!link || !heading || !/^https?:/.test(link.href)) continue;
    var host = '';
    try { host = new URL(link.href).hostname; } catch (e) { continue; }
    if (engineHost.test(host) && !/\/url\?|clck/.test(link.href)) continue;
    var title = clean(heading.innerText);
    if (!title) continue;
    // Поднимаемся до блока результата: он заметно длиннее заголовка.
    var box = heading.parentElement;
    for (var d = 0; d < 6 && box && clean(box.innerText).length < title.length + 60; d++) box = box.parentElement;
    if (!box) continue;
    var text = clean(box.innerText);
    if (ad.test(text) || /(^| )(реклама|sponsored)( |$)/i.test(text.slice(0, 80))) continue;
    var snip = box.querySelector('.OrganicTextContentSpan, .TextContainer, .text-container, .Organic-ContentWrapper, .VwiC3b, .yDYNvb, [data-sncf], .lEBKkf');
    var snippet = snip ? snip.innerText : text.replace(title, '');
    add(title, snippet, link.href);
  }
  return { captcha: captcha, items: out };
})()
