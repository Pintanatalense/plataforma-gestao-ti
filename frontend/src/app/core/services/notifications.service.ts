import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../../environments/environment';
import { Observable, Subject } from 'rxjs';
import { tap } from 'rxjs/operators';
import { AuthService } from './auth.service';

export interface Notification {
  id: string;
  user_id: string;
  title: string;
  message: string;
  type: string;
  is_read: boolean;
  entity_type?: string;
  entity_id?: string;
  created_at: string;
}

@Injectable({
  providedIn: 'root'
})
export class NotificationsService {
  private ws: WebSocket | null = null;
  private newNotificationSubject = new Subject<Notification>();
  
  public newNotification$ = this.newNotificationSubject.asObservable();

  constructor(private http: HttpClient, private authService: AuthService) {
    this.authService.currentUser$.subscribe(user => {
      if (user) {
        this.connectWs();
      } else {
        this.disconnectWs();
      }
    });
  }

  private connectWs() {
    if (this.ws) return;
    
    const token = localStorage.getItem('token');
    if (!token) return;

    // Use ws:// for http and wss:// for https
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // Remove /api/v1 from API URL to get host if needed, or construct manually
    const wsUrl = `${environment.apiUrl.replace('http', 'ws').replace('/api/v1', '')}/api/v1/notifications/ws?token=${token}`;
    
    this.ws = new WebSocket(wsUrl);
    
    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'NEW_NOTIFICATION') {
          this.newNotificationSubject.next(data.payload);
        }
      } catch (e) {
        console.error('Failed to parse WS message', e);
      }
    };
    
    this.ws.onclose = () => {
      this.ws = null;
      // Implementar reconexão se desejado
    };
  }

  private disconnectWs() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  getNotifications(limit: number = 50, offset: number = 0): Observable<Notification[]> {
    return this.http.get<Notification[]>(`${environment.apiUrl}/notifications?limit=${limit}&offset=${offset}`);
  }

  markAsRead(notificationId: string): Observable<Notification> {
    return this.http.post<Notification>(`${environment.apiUrl}/notifications/${notificationId}/read`, {});
  }

  markAllAsRead(): Observable<any> {
    return this.http.post(`${environment.apiUrl}/notifications/read-all`, {});
  }
}
