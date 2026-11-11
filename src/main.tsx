import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import './styles.css';

const queryClient=new QueryClient({defaultOptions:{queries:{staleTime:30_000,retry:1,refetchOnWindowFocus:false},mutations:{retry:false}}});
class ErrorBoundary extends React.Component<{children:React.ReactNode},{error:boolean}> {
  state={error:false};
  static getDerivedStateFromError(){return {error:true};}
  render(){return this.state.error?<main className="boot"><h1>Unable to display this view</h1><p>Your saved database records are unaffected.</p><button onClick={()=>location.reload()}>Reload application</button></main>:this.props.children;}
}
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><ErrorBoundary><QueryClientProvider client={queryClient}><App/></QueryClientProvider></ErrorBoundary></React.StrictMode>);
