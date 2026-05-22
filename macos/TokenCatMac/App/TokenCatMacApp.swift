import SwiftUI

@main
struct TokenCatMacApp: App {
  @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
  @StateObject private var model = MenuBarStatusModel.live()

  var body: some Scene {
    MenuBarExtra {
      MenuBarPopoverView(model: model)
    } label: {
      Label("TokenCat", systemImage: model.menuBarSystemImage)
    }
    .menuBarExtraStyle(.window)
  }
}
