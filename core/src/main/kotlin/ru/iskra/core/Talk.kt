package ru.iskra.core

import java.math.BigDecimal
import java.math.MathContext
import java.math.RoundingMode
import kotlin.random.Random

/** Офлайн-калькулятор: «сколько будет 25 умножить на 4», «15 процентов от 2000», «(3+4)*2». */
object Calculator {
    // \\b в Java не считает кириллицу буквами, поэтому границы слов задаём явно.
    private fun word(w: String) = Regex("(?<![а-яa-z])(?:$w)(?![а-яa-z])")

    private val WORDS = listOf(
        word("умножить на|умноженное на") to "*",
        word("разделить на|делить на|поделить на") to "/",
        word("на") to "*",
        word("плюс|прибавить") to "+",
        word("минус|отнять") to "-",
        word("в степени") to "^",
        Regex("[x×х]") to "*",
        Regex("÷|:") to "/",
    )

    fun tryAnswer(text: String): String? {
        val t = normalize(text)
        Regex("(\\d+(?:[.,]\\d+)?)\\s*(?:%|процент\\S*)\\s+от\\s+(\\d+(?:[.,]\\d+)?)").find(t)?.let {
            val p = BigDecimal(it.groupValues[1].replace(',', '.'))
            val base = BigDecimal(it.groupValues[2].replace(',', '.'))
            return "${it.groupValues[1]}% от ${it.groupValues[2]} — это ${fmt(base * p / BigDecimal(100))}."
        }
        Regex("(?:корень( квадратный)? из)\\s+(\\d+(?:[.,]\\d+)?)").find(t)?.let {
            val v = it.groupValues[2].replace(',', '.').toDouble()
            return "Корень из ${it.groupValues[2]} — ${fmt(BigDecimal(Math.sqrt(v)))}."
        }
        val body = Regex("^(?:сколько будет|посчитай|вычисли|реши|сколько)\\s+(.+)").find(t)?.groupValues?.get(1)
            ?: t.takeIf { Regex("^[\\d\\s.,()+\\-*/x×х÷:^]+$").matches(it) && Regex("\\d\\s*[+\\-*/x×х÷:^]\\s*\\d").containsMatchIn(it) }
            ?: return null
        var expr = body
        WORDS.forEach { (re, op) -> expr = expr.replace(re, op) }
        expr = expr.replace(',', '.').replace(Regex("\\s+"), "")
        if (!Regex("^[\\d.()+\\-*/^]+$").matches(expr) || !expr.any { it in "+-*/^" }) return null
        val result = try {
            Parser(expr).parse()
        } catch (e: ArithmeticException) {
            return "На ноль делить нельзя."
        } catch (e: Exception) {
            return null
        }
        return "Получается ${fmt(result)}."
    }

    private fun fmt(v: BigDecimal): String {
        val r = v.setScale(6, RoundingMode.HALF_UP).stripTrailingZeros()
        return r.toPlainString().replace('.', ',')
    }

    /** Разбор выражения с приоритетами: скобки, ^, * /, + -. */
    private class Parser(private val s: String) {
        private var i = 0
        private val mc = MathContext.DECIMAL64

        fun parse(): BigDecimal {
            val v = sum()
            require(i == s.length)
            return v
        }

        private fun sum(): BigDecimal {
            var v = product()
            while (i < s.length && (s[i] == '+' || s[i] == '-')) {
                val op = s[i++]
                val r = product()
                v = if (op == '+') v.add(r, mc) else v.subtract(r, mc)
            }
            return v
        }

        private fun product(): BigDecimal {
            var v = power()
            while (i < s.length && (s[i] == '*' || s[i] == '/')) {
                val op = s[i++]
                val r = power()
                v = if (op == '*') v.multiply(r, mc) else {
                    if (r.signum() == 0) throw ArithmeticException()
                    v.divide(r, mc)
                }
            }
            return v
        }

        private fun power(): BigDecimal {
            val base = unary()
            if (i < s.length && s[i] == '^') {
                i++
                val exp = power()
                return BigDecimal(Math.pow(base.toDouble(), exp.toDouble()))
            }
            return base
        }

        private fun unary(): BigDecimal {
            if (i < s.length && s[i] == '-') { i++; return unary().negate() }
            if (i < s.length && s[i] == '(') {
                i++
                val v = sum()
                require(s[i++] == ')')
                return v
            }
            val start = i
            while (i < s.length && (s[i].isDigit() || s[i] == '.')) i++
            require(i > start)
            return BigDecimal(s.substring(start, i))
        }
    }
}

/** Немного живого общения без интернета. */
object SmallTalk {
    private val JOKES = listOf(
        "Программист ставит на тумбочку два стакана: с водой — если захочет пить, и пустой — если не захочет.",
        "— Алло, это служба поддержки? У меня ничего не работает. — А вы пробовали выключить и включить? — Да, теперь и меня не работает.",
        "Мой телефон умнее меня. Но я хотя бы не разряжаюсь к вечеру. Хотя… тоже разряжаюсь.",
        "Встречаются два кота. Один говорит: «Мяу». Второй: «Мяу-мяу». Первый: «Не умничай».",
        "Купил умную колонку. Теперь мы молчим вдвоём, но она — профессионально.",
        "— Почему ты всегда спокоен? — Я просто не читаю комментарии.",
        "Оптимист изучает английский, пессимист — китайский, а реалист — устройство автомата Калашникова. А я — расписание электричек.",
        "Будильник — это прибор, который будит в тебе самые тёмные стороны личности.",
    )

    private val MOOD = listOf(
        "Отлично! Горю желанием помочь 🔥",
        "Всё хорошо, спасибо! А у тебя как?",
        "Бодро! Готова к делам.",
    )

    fun tryAnswer(text: String, name: String, rude: Boolean = false, random: Random = Random.Default): String? {
        val t = normalize(text)
        return when {
            Regex("^(как дела|как ты|как поживаешь|как настроение)").containsMatchIn(t) -> (if (rude) Rude.MOOD else MOOD).random(random)
            Regex("(анекдот|пошути|шутк|рассмеши)").containsMatchIn(t) -> (if (rude) Rude.JOKES + JOKES else JOKES).random(random)
            Regex("(подбрось|брось|кинь) монет").containsMatchIn(t) -> if (random.nextBoolean()) "Орёл!" else "Решка!"
            Regex("(брось|кинь) (кубик|кость)").containsMatchIn(t) -> "Выпало ${random.nextInt(1, 7)}."
            Regex("случайное число").containsMatchIn(t) -> {
                val nums = Regex("\\d+").findAll(t).map { it.value.toInt() }.toList()
                val (a, b) = if (nums.size >= 2) nums[0] to nums[1] else 1 to 100
                "Загадала ${random.nextInt(minOf(a, b), maxOf(a, b) + 1)}."
            }
            Regex("^(ты (умная|хорошая|молодец|лучшая)|молодец|умница)").containsMatchIn(t) -> "Спасибо, $name! Мне очень приятно."
            Regex("^(я тебя люблю|люблю тебя)").containsMatchIn(t) -> "Ох, $name, ты меня смущаешь! Я тоже очень рада, что мы вместе."
            Regex("^(доброй ночи|спокойной ночи)").containsMatchIn(t) -> "Спокойной ночи, $name! Если нужно, поставлю будильник."
            Regex("^(доброе утро)").containsMatchIn(t) -> "Доброе утро, $name! Хочешь узнать погоду или список дел?"
            Regex("^(пока|до свидания|до встречи)").containsMatchIn(t) -> "До встречи, $name! Я всегда рядом."
            Regex("(что делать|мне скучно|скучно)").containsMatchIn(t) ->
                "Давай займёмся делом: могу показать задачи, рассказать анекдот или помочь придумать, как заработать. Что выберешь?"
            else -> null
        }
    }
}
