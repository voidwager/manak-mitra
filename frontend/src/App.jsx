import React from 'react';
import { AppProvider, useApp } from './state/AppContext';
import { Sidebar } from './components/layout/Sidebar';
import { Header } from './components/layout/Header';
import { StatusBanner } from './components/layout/StatusBanner';
import { ChatWorkspace } from './pages/ChatWorkspace';
import { AgentsPage } from './pages/AgentsPage';
import { DocumentsPage } from './pages/DocumentsPage';
import { ToolsPage } from './pages/ToolsPage';
import { PerformancePage } from './pages/PerformancePage';
import { SettingsPage } from './pages/SettingsPage';

import { DocumentPreviewModal } from './components/modals/DocumentPreviewModal';
import { DocumentSettingsModal } from './components/modals/DocumentSettingsModal';
import { AgentSettingsModal } from './components/modals/AgentSettingsModal';
import { CreateAgentModal } from './components/modals/CreateAgentModal';
import { ReportModal } from './components/modals/ReportModal';
import { SearchModal } from './components/modals/SearchModal';
import { UserProfileModal } from './components/modals/UserProfileModal';
import { LoginModal } from './components/modals/LoginModal';

const AppContent = () => {
  const { activeTab, activeModal, setActiveModal, isAuthenticated, bootstrapping } = useApp();

  // Avoid flashing the login screen while a stored session is being restored.
  if (bootstrapping) {
    return (
      <div className="app-boot-screen">
        <div className="boot-spinner" />
        <span>Connecting to Manak Mitra...</span>
        <style>{`
          .app-boot-screen {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 16px;
            width: 100%;
            height: 100vh;
            height: 100dvh;
            background-color: var(--bg-app);
            color: var(--text-secondary);
            font-size: 0.875rem;
          }

          .boot-spinner {
            width: 28px;
            height: 28px;
            border-radius: 50%;
            border: 2.5px solid var(--border-subtle);
            border-top-color: var(--accent-primary);
            animation: bootSpin 0.8s linear infinite;
          }

          @keyframes bootSpin {
            to { transform: rotate(360deg); }
          }
        `}</style>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginModal />;
  }

  const renderActivePage = () => {
    switch (activeTab) {
      case 'chat':
        return <ChatWorkspace />;
      case 'agents':
        return <AgentsPage />;
      case 'documents':
        return <DocumentsPage />;
      case 'tools':
        return <ToolsPage />;
      case 'performance':
        return <PerformancePage />;
      case 'settings':
        return <SettingsPage />;
      default:
        return <ChatWorkspace />;
    }
  };

  const renderModal = () => {
    if (!activeModal) return null;

    switch (activeModal.type) {
      case 'docPreview':
        return (
          <DocumentPreviewModal
            docData={activeModal.data}
            onClose={() => setActiveModal(null)}
          />
        );
      case 'docSettings':
        return (
          <DocumentSettingsModal
            docData={activeModal.data}
            onClose={() => setActiveModal(null)}
          />
        );
      case 'createAgent':
        return <CreateAgentModal onClose={() => setActiveModal(null)} />;
      case 'editAgent':
        return (
          <AgentSettingsModal
            agent={activeModal.data}
            onClose={() => setActiveModal(null)}
          />
        );
      case 'report':
        return (
          <ReportModal
            reportData={activeModal.data}
            onClose={() => setActiveModal(null)}
          />
        );
      case 'search':
        return <SearchModal onClose={() => setActiveModal(null)} />;
      case 'profile':
        return <UserProfileModal onClose={() => setActiveModal(null)} />;
      default:
        return null;
    }
  };

  return (
    <div className="app-root-layout">
      {/* Left Navigation Sidebar */}
      <Sidebar />

      {/* Right Main Content Area */}
      <main className="main-content-area">
        <Header />
        <StatusBanner />
        <div className="page-content-wrapper">
          {renderActivePage()}
        </div>
      </main>

      {/* Global Modals */}
      {renderModal()}

      <style>{`
        .app-root-layout {
          display: flex;
          /* 100% rather than 100vw: vw includes the scrollbar gutter, which
             is a horizontal overflow waiting to happen. */
          width: 100%;
          /*
           * dvh, not vh. On a phone 100vh is the height with the browser's
           * URL bar *hidden* - the largest the viewport can ever be - so a
           * 100vh layout is always taller than what is on screen while the
           * bar is showing. Scrolling then shows and hides the bar, the
           * viewport resizes under the layout, and the header appears to
           * jump away. dvh tracks the height actually visible.
           *
           * vh first as the fallback: a browser that does not know dvh
           * ignores the second declaration and keeps the old behaviour.
           */
          height: 100vh;
          height: 100dvh;
          overflow: hidden;
          background-color: var(--bg-app);
        }

        .main-content-area {
          flex: 1;
          display: flex;
          flex-direction: column;
          min-width: 0;
          height: 100vh;
          height: 100dvh;
          overflow: hidden;
          background-color: var(--bg-workspace);
          transition: background-color 0.25s ease;
        }

        .page-content-wrapper {
          flex: 1;
          min-height: 0;
          overflow: hidden;
          position: relative;
        }
      `}</style>
    </div>
  );
};

export function App() {
  return (
    <AppProvider>
      <AppContent />
    </AppProvider>
  );
}

export default App;
