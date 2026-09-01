package com.cjpa.notes.ui.settings

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.cjpa.notes.ui.notes.NoteStatus

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onBack: () -> Unit,
    viewModel: SettingsViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(uiState.saved) {
        if (uiState.saved) {
            snackbarHostState.showSnackbar("Settings saved")
        }
    }

    LaunchedEffect(uiState.errorMessage) {
        val message = uiState.errorMessage
        if (message != null) {
            snackbarHostState.showSnackbar(message)
            viewModel.errorMessageShown()
        }
    }

    // Re-check sign-in/Calendar status whenever the user comes back from the
    // browser (Google's consent screen, or our "signed in" result page).
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) viewModel.refreshStatus()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Settings") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp)
                .verticalScroll(rememberScrollState())
        ) {
            Text(
                text = "Server",
                style = MaterialTheme.typography.titleSmall
            )
            Spacer16()
            OutlinedTextField(
                value = uiState.baseUrl,
                onValueChange = viewModel::onBaseUrlChanged,
                label = { Text("Server base URL") },
                placeholder = { Text("https://notes.example.com") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                modifier = Modifier.fillMaxWidth()
            )

            Spacer16()
            HorizontalDivider()
            Spacer16()

            Text(
                text = "Account",
                style = MaterialTheme.typography.titleSmall
            )
            Text(
                text = "Signing in with Google also connects Google Calendar - a note " +
                    "that mentions a date or time can get a matching event added automatically.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer16()
            if (uiState.isSignedIn) {
                Column {
                    Text(
                        text = uiState.signedInEmail ?: "Signed in",
                        style = MaterialTheme.typography.bodyMedium
                    )
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        when {
                            uiState.isCheckingStatus -> CircularProgressIndicator(modifier = Modifier.height(16.dp))
                            uiState.calendarLinked -> Text(
                                "Calendar connected",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.primary
                            )
                            else -> Text(
                                "Calendar not connected",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                    Spacer16()
                    Row {
                        OutlinedButton(onClick = viewModel::signIn) {
                            Text("Re-connect")
                        }
                        Spacer(Modifier.width(12.dp))
                        TextButton(onClick = viewModel::signOut) {
                            Text("Sign out")
                        }
                    }
                }
            } else {
                Button(onClick = viewModel::signIn, enabled = uiState.baseUrl.isNotBlank()) {
                    Text("Sign in with Google")
                }
            }

            Spacer16()
            HorizontalDivider()
            Spacer16()

            Text(
                text = "Show statuses",
                style = MaterialTheme.typography.titleSmall
            )
            Text(
                text = "Choose which note statuses appear in the list.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            NoteStatus.entries.forEach { status ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(
                        checked = status in uiState.enabledStatuses,
                        onCheckedChange = { checked -> viewModel.onStatusFilterToggled(status, checked) }
                    )
                    Text(status.displayLabel)
                }
            }

            Spacer16()
            Button(onClick = viewModel::save) {
                Text("Save")
            }
        }
    }
}

@Composable
private fun Spacer16() {
    Spacer(Modifier.height(16.dp))
}
