import { createContext, useContext, useReducer } from 'react'
import { graphReducer, INITIAL_GRAPH_STATE } from './graphReducer'
import type { GraphState } from './graphReducer'

interface GraphContextValue {
  state: GraphState
  dispatch: React.Dispatch<import('./graphReducer').GraphAction>
}

export const GraphContext = createContext<GraphContextValue>({
  state: INITIAL_GRAPH_STATE,
  dispatch: () => null,
})

export function GraphProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(graphReducer, INITIAL_GRAPH_STATE)
  return (
    <GraphContext.Provider value={{ state, dispatch }}>
      {children}
    </GraphContext.Provider>
  )
}

export function useGraph() {
  return useContext(GraphContext)
}
