import AVFoundation
import SwiftUI

@main
struct karaokeApp: App {
    @State private var config = AppConfig()
    @State private var session = PlayerSession()

    init() {
        // Karaoke has to come out of the speakers even with the ring switch
        // silenced, and keep going when the screen locks.
        let audio = AVAudioSession.sharedInstance()
        try? audio.setCategory(.playback, mode: .moviePlayback)
        try? audio.setActive(true)
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(config)
                .environment(session)
        }
    }
}
