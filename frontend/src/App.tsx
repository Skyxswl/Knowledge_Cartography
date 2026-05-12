import { BrowserRouter, Route, Routes } from 'react-router-dom'
import LearningPage from './pages/LearningPage'
import TopicInputPage from './pages/TopicInputPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<TopicInputPage />} />
        <Route path="/learn/:sessionId" element={<LearningPage />} />
      </Routes>
    </BrowserRouter>
  )
}
