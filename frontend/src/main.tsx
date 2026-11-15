import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './SiteApp'
import CandidateInterview from './CandidateInterview'
import CandidateTextInterview from './CandidateTextInterview'
import GoalWorkspace from './GoalWorkspace'
import './styles.css'
import './refinement.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#214f43',
          colorInfo: '#456b80',
          colorSuccess: '#377c66',
          colorWarning: '#aa7b38',
          colorError: '#b35750',
          colorText: '#2d4038',
          colorTextSecondary: '#6a7a72',
          colorTextPlaceholder: '#84918b',
          colorBorder: '#dce4de',
          colorBgLayout: '#f3f5f2',
          colorBgContainer: '#ffffff',
          borderRadius: 9,
          controlHeight: 38,
          motionDurationFast: '0.12s',
          motionDurationMid: '0.2s',
          motionDurationSlow: '0.28s',
          motionEaseInOut: 'cubic-bezier(0.22, 1, 0.36, 1)',
          fontFamily: 'Inter, "Microsoft YaHei", "PingFang SC", sans-serif',
        },
        components: {
          Button: { primaryShadow: '0 2px 3px rgba(23, 59, 46, 0.12)', fontWeight: 500 },
          Input: { activeShadow: '0 0 0 3px rgba(33, 79, 67, 0.08)' },
          Select: { optionSelectedBg: '#edf3ef' },
          Table: { headerBg: '#f5f7f4', rowHoverBg: '#f2f6f3', borderColor: '#e8ede8' },
          Tabs: { inkBarColor: '#214f43', itemSelectedColor: '#214f43' },
          Modal: { borderRadiusLG: 16 },
          Drawer: { footerPaddingBlock: 16 },
        },
      }}
    >
      {window.location.pathname === '/candidate/text' ? <CandidateTextInterview /> : window.location.pathname === '/candidate' ? <CandidateInterview /> : window.location.pathname === '/goal' ? <GoalWorkspace /> : <App />}
    </ConfigProvider>
  </StrictMode>,
)
