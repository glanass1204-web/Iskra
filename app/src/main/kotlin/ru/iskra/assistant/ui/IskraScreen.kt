package ru.iskra.assistant.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.PrimaryScrollableTabRow
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import ru.iskra.assistant.AssistantViewModel
import ru.iskra.core.ChatLine
import ru.iskra.core.EntryKind
import ru.iskra.core.IskraData
import ru.iskra.core.Speaker
import ru.iskra.core.formatMoney
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val TABS = listOf("Чат", "Задачи", "Память", "Заработок", "Настройки")
private val stamp = SimpleDateFormat("d MMM, HH:mm", Locale.forLanguageTag("ru-RU"))

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun IskraScreen(vm: AssistantViewModel, onExport: () -> Unit) {
    val data by vm.data.collectAsStateWithLifecycle()
    val busy by vm.busy.collectAsStateWithLifecycle()
    val online by vm.online.collectAsStateWithLifecycle()
    val listening by vm.voice.listening.collectAsStateWithLifecycle()
    val partial by vm.voice.partial.collectAsStateWithLifecycle()
    val confirm by vm.confirm.collectAsStateWithLifecycle()
    var tab by rememberSaveable { mutableIntStateOf(0) }

    Column(
        Modifier
            .fillMaxSize()
            .background(Brush.verticalGradient(listOf(androidx.compose.ui.graphics.Color(0xFF2A160B), Coal, Coal)))
            .statusBarsPadding()
            .navigationBarsPadding()
            .imePadding(),
    ) {
        Header(
            status = when {
                listening -> "Слушаю…"
                busy -> "Думаю…"
                online -> "Готова"
                else -> "Готова · офлайн-режим"
            },
            online = online,
        )
        PrimaryScrollableTabRow(selectedTabIndex = tab, containerColor = androidx.compose.ui.graphics.Color.Transparent, edgePadding = 12.dp) {
            TABS.forEachIndexed { i, title ->
                Tab(selected = tab == i, onClick = { tab = i }, text = { Text(title) })
            }
        }
        Box(Modifier.weight(1f)) {
            when (tab) {
                0 -> Chat(data.chat, onChip = vm::submit)
                1 -> TasksTab(data, vm)
                2 -> MemoryTab(data, vm)
                3 -> MoneyTab(data, vm)
                else -> SettingsTab(data, vm, onExport)
            }
        }
        if (tab == 0) Composer(listening = listening, partial = partial, onSend = vm::submit, onMic = vm::listen)
    }

    confirm?.let { request ->
        AlertDialog(
            onDismissRequest = { vm.answerConfirm(false) },
            title = { Text("Подтверди действие", color = Ember, fontWeight = FontWeight.Bold) },
            text = { Text(request.text) },
            confirmButton = { TextButton(onClick = { vm.answerConfirm(true) }) { Text("Да, выполнить") } },
            dismissButton = { TextButton(onClick = { vm.answerConfirm(false) }) { Text("Отмена") } },
            containerColor = Surface2,
        )
    }
}

@Composable
private fun Header(status: String, online: Boolean) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier.size(38.dp).clip(RoundedCornerShape(12.dp))
                .background(Brush.radialGradient(listOf(Glow, Ember, EmberDeep))),
        )
        Column(Modifier.padding(start = 12.dp).weight(1f)) {
            Text("Искра", fontSize = 20.sp, fontWeight = FontWeight.Bold)
            Text(status, fontSize = 13.sp, color = Muted)
        }
        Text(
            if (online) "онлайн" else "офлайн",
            fontSize = 12.sp,
            color = if (online) Ok else Muted,
            modifier = Modifier.border(1.dp, if (online) Ok.copy(alpha = .5f) else Line, CircleShape)
                .padding(horizontal = 10.dp, vertical = 4.dp),
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Chat(lines: List<ChatLine>, onChip: (String) -> Unit) {
    val state = rememberLazyListState()
    val context = LocalContext.current
    LaunchedEffect(lines.size) { if (lines.isNotEmpty()) state.animateScrollToItem(lines.size) }
    LazyColumn(state = state, modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        items(lines) { line ->
            val mine = line.who == Speaker.ME
            Row(Modifier.fillMaxWidth(), horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start) {
                Column(
                    Modifier.widthIn(max = 320.dp)
                        .clip(RoundedCornerShape(18.dp, 18.dp, if (mine) 6.dp else 18.dp, if (mine) 18.dp else 6.dp))
                        .background(if (mine) Ember else Surface2)
                        .padding(horizontal = 14.dp, vertical = 10.dp),
                ) {
                    Text(line.text, color = if (mine) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface)
                    line.link?.let { url ->
                        Text(
                            "Открыть в браузере",
                            color = if (mine) MaterialTheme.colorScheme.onPrimary else Ember,
                            textDecoration = TextDecoration.Underline,
                            modifier = Modifier.padding(top = 6.dp).clickable {
                                context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                            },
                        )
                    }
                }
            }
        }
        item {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(vertical = 8.dp)) {
                listOf("Что ты умеешь?", "Мои задачи", "Заряд батареи", "Включи фонарик", "Баланс").forEach { chip ->
                    Text(
                        chip,
                        fontSize = 14.sp,
                        modifier = Modifier.clip(CircleShape).border(1.dp, Line, CircleShape).background(Surface1)
                            .clickable { onChip(chip) }.padding(horizontal = 12.dp, vertical = 6.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun Composer(listening: Boolean, partial: String, onSend: (String) -> Unit, onMic: () -> Unit) {
    var text by remember { mutableStateOf("") }
    val pulse = rememberInfiniteTransition(label = "pulse")
    val scale by pulse.animateFloat(1f, if (listening) 1.12f else 1f, infiniteRepeatable(tween(600), RepeatMode.Reverse), label = "scale")
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        OutlinedTextField(
            value = if (listening && partial.isNotEmpty()) partial else text,
            onValueChange = { text = it },
            placeholder = { Text(if (listening) "Говори…" else "Скажи или напиши…") },
            modifier = Modifier.weight(1f),
            shape = CircleShape,
            singleLine = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(onSend = { onSend(text); text = "" }),
            trailingIcon = {
                if (text.isNotBlank()) {
                    IconButton(onClick = { onSend(text); text = "" }) { Icon(Icons.AutoMirrored.Filled.Send, "Отправить") }
                }
            },
        )
        Spacer(Modifier.size(10.dp))
        Box(
            Modifier.size(62.dp).scale(scale).clip(CircleShape)
                .background(Brush.radialGradient(listOf(Glow, Ember, EmberDeep)))
                .clickable(onClick = onMic),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                if (listening) Icons.Filled.Stop else Icons.Filled.Mic,
                contentDescription = if (listening) "Остановить" else "Говорить",
                tint = MaterialTheme.colorScheme.onPrimary,
                modifier = Modifier.size(30.dp),
            )
        }
    }
}

@Composable
private fun Section(title: String) {
    Text(title, color = Muted, fontWeight = FontWeight.SemiBold, fontSize = 15.sp, modifier = Modifier.padding(top = 18.dp, bottom = 8.dp))
}

@Composable
private fun Item(text: String, sub: String? = null, done: Boolean? = null, onToggle: (() -> Unit)? = null, onDelete: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(bottom = 8.dp).clip(RoundedCornerShape(14.dp)).background(Surface1)
            .border(1.dp, Line, RoundedCornerShape(14.dp)).padding(horizontal = 8.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (done != null && onToggle != null) Checkbox(checked = done, onCheckedChange = { onToggle() })
        Column(Modifier.weight(1f).padding(horizontal = 6.dp, vertical = 6.dp)) {
            Text(text, color = if (done == true) Muted else MaterialTheme.colorScheme.onSurface,
                textDecoration = if (done == true) TextDecoration.LineThrough else null)
            sub?.let { Text(it, color = Muted, fontSize = 12.sp) }
        }
        IconButton(onClick = onDelete) { Icon(Icons.Filled.Close, "Удалить", tint = Muted) }
    }
}

@Composable
private fun Empty(text: String) {
    Text(text, color = Muted, modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp))
}

@Composable
private fun Scrollable(content: @Composable () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 4.dp)) { content() }
}

@Composable
private fun TasksTab(data: IskraData, vm: AssistantViewModel) = Scrollable {
    Section("Задачи")
    if (data.tasks.isEmpty()) Empty("Задач нет — скажи «задача …»")
    data.tasks.sortedBy { it.done }.forEach { t ->
        Item(t.text, done = t.done, onToggle = { vm.toggleTask(t.id) }, onDelete = { vm.delete("task", t.id, t.text) })
    }
    Section("Напоминания")
    if (data.pendingReminders.isEmpty()) Empty("Нет активных напоминаний")
    data.pendingReminders.forEach { r ->
        Item(r.text, sub = stamp.format(Date(r.due)), onDelete = { vm.delete("reminder", r.id, r.text) })
    }
}

@Composable
private fun MemoryTab(data: IskraData, vm: AssistantViewModel) = Scrollable {
    Section("Что я о тебе помню")
    if (data.memory.isEmpty()) Empty("Скажи «запомни, что …»")
    data.memory.forEach { f -> Item(f.text, sub = stamp.format(Date(f.at)), onDelete = { vm.delete("memory", f.id, f.text) }) }
    Section("Мониторинг")
    if (data.watches.isEmpty()) Empty("Скажи «следи за …»")
    data.watches.forEach { w ->
        Item(w.query, sub = if (w.checkedAt > 0) "проверено ${stamp.format(Date(w.checkedAt))}" else "ещё не проверялось",
            onDelete = { vm.delete("watch", w.id, w.query) })
    }
}

@Composable
private fun MoneyTab(data: IskraData, vm: AssistantViewModel) = Scrollable {
    Section("Проекты и заработок")
    val income = data.ledger.filter { it.kind == EntryKind.INCOME }.sumOf { it.amount }
    val expense = data.ledger.filter { it.kind == EntryKind.EXPENSE }.sumOf { it.amount }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        listOf("Доход" to income, "Расход" to expense, "Итого" to income - expense).forEach { (label, value) ->
            Column(Modifier.weight(1f).clip(RoundedCornerShape(14.dp)).background(Surface1).border(1.dp, Line, RoundedCornerShape(14.dp)).padding(10.dp)) {
                Text(formatMoney(value), fontWeight = FontWeight.Bold, fontSize = 16.sp)
                Text(label, color = Muted, fontSize = 12.sp)
            }
        }
    }
    Section("Записи")
    if (data.ledger.isEmpty()) Empty("Скажи «доход 5000 проект …»")
    data.ledger.reversed().forEach { e ->
        val sign = if (e.kind == EntryKind.INCOME) "+" else "−"
        Item("$sign${formatMoney(e.amount)} · ${e.project}", sub = stamp.format(Date(e.at)), onDelete = { vm.delete("entry", e.id, "$sign${formatMoney(e.amount)}") })
    }
}

@Composable
private fun SettingsTab(data: IskraData, vm: AssistantViewModel, onExport: () -> Unit) = Scrollable {
    val s = data.settings
    var name by remember(s.name) { mutableStateOf(s.name) }
    var key by remember(s.apiKey) { mutableStateOf(s.apiKey) }
    Section("Настройки")
    OutlinedTextField(
        value = name, onValueChange = { name = it }, singleLine = true, modifier = Modifier.fillMaxWidth(),
        label = { Text("Как к тебе обращаться") },
        keyboardActions = KeyboardActions(onDone = { vm.updateSettings { it.copy(name = name.trim().ifEmpty { "дружище" }) } }),
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
    )
    Spacer(Modifier.size(12.dp))
    OutlinedTextField(
        value = key, onValueChange = { key = it }, singleLine = true, modifier = Modifier.fillMaxWidth(),
        label = { Text("Ключ Claude API (необязательно)") },
        placeholder = { Text("sk-ant-…") },
        visualTransformation = PasswordVisualTransformation(),
        supportingText = { Text("Включает «умный» режим и поиск в интернете, когда есть сеть. Запросы платные.") },
        keyboardActions = KeyboardActions(onDone = { vm.updateSettings { it.copy(apiKey = key.trim()) } }),
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
    )
    OutlinedButton(
        onClick = { vm.updateSettings { it.copy(name = name.trim().ifEmpty { "дружище" }, apiKey = key.trim()) } },
        modifier = Modifier.padding(top = 4.dp),
    ) { Text("Сохранить") }
    SwitchRow("Отвечать голосом", s.voiceReplies) { v -> vm.updateSettings { it.copy(voiceReplies = v) } }
    SwitchRow("Слушать сразу при открытии", s.autoListen) { v -> vm.updateSettings { it.copy(autoListen = v) } }

    Section("Быстрый вызов")
    Text(
        "• Двойное нажатие боковой кнопки: Настройки → Дополнительные функции → Боковая кнопка → Двойное нажатие → Открыть приложение → Искра (включи «Слушать сразу при открытии»).\n" +
            "• Плитка «Искра» в шторке: потяни шторку вниз → ✎ → перетащи плитку.\n" +
            "• Долгое нажатие на иконку → «Сказать Искре».",
        color = Muted, fontSize = 14.sp,
    )

    Section("Данные")
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = onExport) { Text("Экспорт") }
        OutlinedButton(onClick = vm::wipe) { Text("Стереть всё", color = MaterialTheme.colorScheme.error) }
    }
    Text(
        "Все данные хранятся только на этом телефоне. Ключ API отправляется только в Anthropic.",
        color = Muted, fontSize = 13.sp, modifier = Modifier.padding(vertical = 12.dp),
    )
}

@Composable
private fun SwitchRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, modifier = Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChange)
    }
}
