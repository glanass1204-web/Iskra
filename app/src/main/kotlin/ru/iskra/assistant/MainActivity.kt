package ru.iskra.assistant

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CompletableDeferred
import ru.iskra.assistant.ui.IskraScreen
import ru.iskra.assistant.ui.IskraTheme

class MainActivity : ComponentActivity() {
    private val vm: AssistantViewModel by viewModels()

    private var pendingPermissions: CompletableDeferred<Boolean>? = null
    private val permissionLauncher = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
        pendingPermissions?.complete(result.values.all { it })
        pendingPermissions = null
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        vm.gate = PermissionGate { permissions ->
            val missing = permissions.filter {
                ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
            }
            if (missing.isEmpty()) return@PermissionGate true
            val deferred = CompletableDeferred<Boolean>()
            pendingPermissions?.complete(false)
            pendingPermissions = deferred
            permissionLauncher.launch(missing.toTypedArray())
            deferred.await()
        }
        setContent {
            IskraTheme {
                IskraScreen(vm, onExport = ::shareExport)
            }
        }
        // Два запроса разрешений одновременно Android не покажет, поэтому уведомления — только если не слушаем сразу.
        if (savedInstanceState == null && !handleLaunch(intent)) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
            ) {
                permissionLauncher.launch(arrayOf(Manifest.permission.POST_NOTIFICATIONS))
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleLaunch(intent)
    }

    /** Если Искру вызвали как помощника (кнопка, плитка, ярлык) — сразу слушаем. */
    private fun handleLaunch(intent: Intent?): Boolean {
        val asAssistant = intent?.action in setOf(Intent.ACTION_ASSIST, Intent.ACTION_VOICE_COMMAND, ACTION_LISTEN)
        val listen = asAssistant || vm.data.value.settings.autoListen
        if (listen) vm.listen()
        return listen
    }

    private fun shareExport() {
        val send = Intent(Intent.ACTION_SEND)
            .setType("application/json")
            .putExtra(Intent.EXTRA_SUBJECT, "Искра — мои данные")
            .putExtra(Intent.EXTRA_TEXT, vm.exportJson())
        startActivity(Intent.createChooser(send, "Сохранить данные Искры"))
    }

    companion object {
        const val ACTION_LISTEN = "ru.iskra.assistant.LISTEN"
    }
}
