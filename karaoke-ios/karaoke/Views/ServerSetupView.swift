import SwiftUI

/// First-run screen: point the iPad at karaoke-server on the LAN. The address
/// is remembered, so this is normally seen exactly once.
struct ServerSetupView: View {
    @Environment(AppConfig.self) private var config

    @State private var address = ""
    @State private var checking = false
    @State private var error: String?
    @FocusState private var addressFocused: Bool

    var body: some View {
        VStack(spacing: 24) {
            Image(systemName: "music.mic")
                .font(.system(size: 64))
                .foregroundStyle(.tint)
            Text("Connect to karaoke-server")
                .font(.largeTitle.weight(.bold))
            Text("Enter the address of the machine running karaoke-server on this network.")
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            TextField("192.168.0.109:8787", text: $address)
                .textFieldStyle(.roundedBorder)
                .font(.title3.monospaced())
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .submitLabel(.go)
                .focused($addressFocused)
                .onSubmit { Task { await connect() } }
                .frame(maxWidth: 420)

            if let error {
                Text(error)
                    .font(.callout)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
            }

            Button {
                Task { await connect() }
            } label: {
                if checking {
                    ProgressView().frame(width: 80)
                } else {
                    Text("Connect").frame(width: 80)
                }
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(address.trimmingCharacters(in: .whitespaces).isEmpty || checking)

            Text("Port 8787 is assumed if you leave it off.")
                .font(.footnote)
                .foregroundStyle(.tertiary)
        }
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear { addressFocused = true }
    }

    private func connect() async {
        guard let normalized = AppConfig.normalize(address), let url = URL(string: normalized) else {
            error = "That doesn't look like an address."
            return
        }
        checking = true
        error = nil
        defer { checking = false }
        // Verify before saving, so a typo is caught here rather than as an
        // empty library later.
        if await APIClient(base: url).ping() {
            config.setServerBase(normalized)
        } else {
            error = "No karaoke-server answered at \(normalized).\nCheck it is running and bound to 0.0.0.0."
        }
    }
}
