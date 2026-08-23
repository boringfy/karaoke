import SwiftUI

struct ContentView: View {
    @Environment(AppConfig.self) private var config

    var body: some View {
        if config.isConfigured {
            LibraryView()
        } else {
            ServerSetupView()
        }
    }
}

#Preview {
    ContentView()
        .environment(AppConfig())
        .environment(PlayerSession())
}
