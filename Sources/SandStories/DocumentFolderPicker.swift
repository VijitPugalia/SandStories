import SwiftUI
import UniformTypeIdentifiers
import UIKit

/// Presents `UIDocumentPickerViewController` in **folder** open mode (USB-C volumes, Files app).
struct DocumentFolderPicker: UIViewControllerRepresentable {
    var onPicked: (URL) -> Void
    var onCancelled: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onPicked: onPicked, onCancelled: onCancelled)
    }

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.folder], asCopy: false)
        picker.delegate = context.coordinator
        picker.allowsMultipleSelection = false
        return picker
    }

    func updateUIViewController(_ uiViewController: UIDocumentPickerViewController, context: Context) {}

    final class Coordinator: NSObject, UIDocumentPickerDelegate {
        let onPicked: (URL) -> Void
        let onCancelled: () -> Void

        init(onPicked: @escaping (URL) -> Void, onCancelled: @escaping () -> Void) {
            self.onPicked = onPicked
            self.onCancelled = onCancelled
        }

        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            guard let url = urls.first else {
                onCancelled()
                return
            }
            _ = url.startAccessingSecurityScopedResource()
            onPicked(url)
        }

        func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
            onCancelled()
        }
    }
}
