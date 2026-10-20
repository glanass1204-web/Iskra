package ru.iskra.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.nio.file.Files
import java.time.LocalDateTime
import java.time.ZoneOffset

class BrainTest {
    private val now = LocalDateTime.of(2026, 10, 20, 12, 0)
    private lateinit var store: Store
    private lateinit var brain: Brain

    @Before
    fun setUp() {
        store = Store(null)
        brain = Brain(store, ZoneOffset.UTC) { now }
    }

    @Test
    fun parsesRelativeAndAbsoluteTimes() {
        assertEquals(now.plusMinutes(10), parseWhen("через 10 минут позвонить", now)!!.at)
        assertEquals(now.plusMinutes(5), parseWhen("через пять минут", now)!!.at)
        assertEquals(now.plusHours(1), parseWhen("через час", now)!!.at)
        assertEquals(now.plusMinutes(30), parseWhen("через полчаса", now)!!.at)
        assertEquals(now.withHour(19), parseWhen("в 7 вечера", now)!!.at)
        assertEquals(now.plusDays(1).withHour(9).withMinute(15), parseWhen("завтра в 9:15", now)!!.at)
        // Время, которое сегодня уже прошло, переносится на завтра.
        assertEquals(now.plusDays(1).withHour(8), parseWhen("в 8", now)!!.at)
        assertNull(parseWhen("когда-нибудь", now))
    }

    @Test
    fun remembersAndForgetsFacts() {
        assertEquals("Запомнила: «я люблю кофе».", brain.handle("Запомни, что я люблю кофе").text)
        assertTrue(brain.handle("что ты помнишь").text.contains("я люблю кофе"))
        val forget = brain.handle("забудь кофе").action as DeviceAction.Forget
        assertEquals(listOf("я люблю кофе"), forget.preview)
        // Удаление выполняет приложение после подтверждения, сам мозг ничего не стирает.
        assertEquals(1, store.value.memory.size)
    }

    @Test
    fun managesTasks() {
        brain.handle("Задача купить хлеб")
        brain.handle("надо позвонить в банк")
        assertTrue(brain.handle("мои задачи").text.contains("2. позвонить в банк"))
        brain.handle("готово 1")
        assertEquals(listOf("позвонить в банк"), store.value.openTasks.map { it.text })
    }

    @Test
    fun schedulesReminders() {
        val reply = brain.handle("Напомни через 10 минут проверить почту")
        assertEquals("Напомню сегодня в 12:10: «проверить почту».", reply.text)
        val r = store.value.reminders.single()
        assertEquals(now.plusMinutes(10).toInstant(ZoneOffset.UTC).toEpochMilli(), r.due)
        assertTrue(brain.handle("напомни завтра в 9 утра тренировка").text.startsWith("Напомню завтра в 09:00"))
    }

    @Test
    fun phoneActionsNeedConfirmation() {
        val call = brain.handle("Позвони 8 999 123-45-67").action as DeviceAction.Call
        assertEquals("89991234567", call.who)
        assertTrue(call.confirm != null)
        assertEquals("мама", (brain.handle("позвони мама").action as DeviceAction.Call).who)

        val sms = brain.handle("Напиши СМС 89991234567 Буду в 7").action as DeviceAction.SendSms
        assertEquals("89991234567", sms.who)
        assertEquals("Буду в 7", sms.body)
        assertTrue(sms.confirm != null)

        assertNull(brain.handle("включи фонарик").action!!.confirm)
    }

    @Test
    fun recognisesDeviceCommands() {
        assertEquals(DeviceAction.Flashlight(true), brain.handle("Включи фонарик").action)
        assertEquals(DeviceAction.SetAlarm(7, 30, "Искра"), brain.handle("будильник на 7:30").action)
        assertEquals(DeviceAction.SetTimer(300, "Искра"), brain.handle("таймер на 5 минут").action)
        assertEquals(DeviceAction.OpenApp("телеграм"), brain.handle("Открой Телеграм").action)
        assertEquals(DeviceAction.OpenSettings(DeviceAction.OpenSettings.Panel.WIFI), brain.handle("включи вайфай").action)
        assertEquals(DeviceAction.Navigate("красная площадь"), brain.handle("маршрут до красная площадь").action)
        assertEquals(DeviceAction.Battery, brain.handle("какой заряд батареи").action)
    }

    @Test
    fun tracksMoneyByProject() {
        assertEquals("Доход 5 000 ₽ записан в «Сайт».", brain.handle("доход 5000 проект Сайт").text)
        brain.handle("расход 300")
        val balance = brain.handle("баланс").text
        assertTrue(balance, balance.startsWith("Итого: 4 700 ₽"))
        assertTrue(balance.contains("• Сайт: 5 000 ₽"))
    }

    @Test
    fun keepsNameCase() {
        assertEquals("Приятно познакомиться, Саша! Буду так к тебе обращаться.", brain.handle("меня зовут Саша").text)
        assertEquals("Саша", store.value.settings.name)
    }

    @Test
    fun casualGreetingDoesNotTriggerWebSearch() {
        for (phrase in listOf("Ну как твои дела?", "Как у тебя дела?", "Как дела?", "Слушай, как настроение?")) {
            val reply = brain.handle(phrase)
            assertNull("Не должен искать в интернете: $phrase", reply.online)
            assertTrue("Должен ответить по-человечески: $phrase", reply.text.isNotBlank())
        }
    }

    @Test
    fun unknownQuestionsGoOnline() {
        val r = brain.handle("Объясни теорию относительности")
        assertEquals(OnlineRequest.Ask("Объясни теорию относительности"), r.online)
        assertEquals("погоду в москве", (brain.handle("найди погоду в Москве").online as OnlineRequest.Ask).searchHint)
    }

    @Test
    fun onlineHelperSearchesWithoutKeyAndWatchesForChanges() {
        var rate = "80.0"
        val http = Http { url ->
            if (url.contains("cbr-xml-daily")) """{"Valute":{"USD":{"Nominal":1,"Name":"Доллар США","Value":$rate}}}""" else null
        }
        val helper = OnlineHelper(store, knowledge = Knowledge(http))
        assertEquals("Курс ЦБ: Доллар США — 80,00 ₽.", helper.answer(OnlineRequest.Ask("курс доллара")).text)
        brain.handle("следи за курсом доллара")
        assertTrue(helper.checkWatches(1).first.contains("запомнила текущее состояние"))
        assertEquals(emptyList<String>(), helper.checkWatches(2).second)
        rate = "81.5"
        assertEquals(listOf("курсом доллара"), helper.checkWatches(3).second)
    }

    @Test
    fun persistsToDisk() {
        val file = File(Files.createTempDirectory("iskra").toFile(), "data.json")
        Store(file).update { it.copy(memory = listOf(Fact(text = "тест", at = 1))) }
        assertEquals("тест", Store(file).value.memory.single().text)
    }
}
