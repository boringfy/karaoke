import AVFoundation
import SwiftUI
import UIKit

/// The MV, filling the screen behind the lyrics. A bare `AVPlayerLayer` rather
/// than `VideoPlayer` — the engine owns the transport, and the system playback
/// controls must not appear over the karaoke overlay.
struct VideoLayerView: UIViewRepresentable {
    let player: AVPlayer?

    func makeUIView(context: Context) -> PlayerLayerView {
        let view = PlayerLayerView()
        view.backgroundColor = .black
        // Fit the whole frame, never crop: a 16:9 MV on a 4:3 iPad loses a
        // sixth of its width to .resizeAspectFill, and burned-in lyrics or a
        // singer at the edge go with it. The desktop player does the same
        // (object-fit: contain).
        view.playerLayer.videoGravity = .resizeAspect
        view.playerLayer.player = player
        return view
    }

    func updateUIView(_ view: PlayerLayerView, context: Context) {
        if view.playerLayer.player !== player {
            view.playerLayer.player = player
        }
    }

    final class PlayerLayerView: UIView {
        override static var layerClass: AnyClass { AVPlayerLayer.self }
        var playerLayer: AVPlayerLayer { layer as! AVPlayerLayer }
    }
}
