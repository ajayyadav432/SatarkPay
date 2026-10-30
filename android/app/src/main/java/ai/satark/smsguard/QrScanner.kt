package ai.satark.smsguard

import android.content.Context
import android.net.Uri
import android.util.Log
import androidx.annotation.OptIn
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/** Finds QR codes on the phone itself. Nothing leaves the phone until the person presses "Check". */
private fun qrClient() = BarcodeScanning.getClient(BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build())

/** Reads a QR code from a photo or screenshot. text is null when there is none. */
fun readQrFromImage(context: Context, uri: Uri, done: (String?) -> Unit) {
    val client = qrClient()
    val image = try { InputImage.fromFilePath(context, uri) } catch (e: Exception) { Log.w("SatarkPay", "Cannot open the picture", e); done(null); return }
    client.process(image)
        .addOnSuccessListener { codes -> done(codes.firstOrNull { !it.rawValue.isNullOrEmpty() }?.rawValue) }
        .addOnFailureListener { Log.w("SatarkPay", "Cannot read the picture", it); done(null) }
        .addOnCompleteListener { client.close() }
}

/** The live camera. Calls onFound once, with the text of the first QR code it sees. */
@OptIn(ExperimentalGetImage::class)
@Composable
fun QrCamera(modifier: Modifier, onFound: (String) -> Unit) {
    val context = LocalContext.current
    val owner = LocalLifecycleOwner.current
    val view = remember { PreviewView(context) }
    DisposableEffect(owner) {
        val client = qrClient()
        val worker = Executors.newSingleThreadExecutor()
        val found = AtomicBoolean(false)
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            val provider = future.get()
            val preview = Preview.Builder().build().also { it.surfaceProvider = view.surfaceProvider }
            val analysis = ImageAnalysis.Builder().setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()
            analysis.setAnalyzer(worker) { frame ->
                val media = frame.image
                if (media == null || found.get()) { frame.close(); return@setAnalyzer }
                client.process(InputImage.fromMediaImage(media, frame.imageInfo.rotationDegrees))
                    .addOnSuccessListener { codes ->
                        val text = codes.firstOrNull { !it.rawValue.isNullOrEmpty() }?.rawValue
                        if (text != null && found.compareAndSet(false, true)) onFound(text)
                    }
                    .addOnCompleteListener { frame.close() }
            }
            provider.unbindAll()
            provider.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
        }, ContextCompat.getMainExecutor(context))
        onDispose {
            found.set(true)
            future.addListener({ future.get().unbindAll() }, ContextCompat.getMainExecutor(context))
            worker.shutdown()
            client.close()
        }
    }
    AndroidView(factory = { view }, modifier = modifier)
}
