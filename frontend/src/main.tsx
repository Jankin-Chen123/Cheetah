import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import GoalWorkspace from './GoalWorkspace'
import CandidateInterview from './CandidateInterview'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#355e46',
          colorText: '#42563f',
          colorBorder: '#e0e7da',
          borderRadius: 7,
          controlHeight: 36,
          fontFamily: 'Inter, "Microsoft YaHei", "PingFang SC", sans-serif',
        },
      }}
    >
      {window.location.pathname === '/candidate' ? <CandidateInterview /> : window.location.pathname === '/goal' ? <GoalWorkspace /> : <App />}
    </ConfigProvider>
  </StrictMode>,
)
