import ARKit

/// Forwards `ARSessionDelegate` callbacks to multiple delegates.
final class ARSessionDelegateMultiplexer: NSObject, ARSessionDelegate {
    private let delegates: [any ARSessionDelegate]

    init(_ delegates: [any ARSessionDelegate]) {
        self.delegates = delegates
        super.init()
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        for delegate in delegates {
            delegate.session?(session, didUpdate: frame)
        }
    }
}

