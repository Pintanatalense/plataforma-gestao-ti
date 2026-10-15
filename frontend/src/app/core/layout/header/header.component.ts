import { Component, EventEmitter, OnInit, Output, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatMenuModule } from '@angular/material/menu';
import { MatDividerModule } from '@angular/material/divider';
import { MatBadgeModule } from '@angular/material/badge';
import { MatTooltipModule } from '@angular/material/tooltip';

import { HttpClient } from '@angular/common/http';
import { AuthService } from '../../auth/auth.service';
import { Notification, NotificationsService } from '../../services/notifications.service';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatToolbarModule,
    MatIconModule,
    MatButtonModule,
    MatMenuModule,
    MatDividerModule,
    MatBadgeModule,
    MatTooltipModule
  ],
  template: `
    <mat-toolbar class="header-toolbar">
      <button mat-icon-button (click)="toggleSidenav.emit()" aria-label="Toggle menu" class="menu-btn">
        <mat-icon>menu</mat-icon>
      </button>
      
      <span class="spacer"></span>

      <!-- Demo Mode Badge -->
      <div *ngIf="isDemoMode" class="demo-badge" matTooltip="Ambiente de Demonstração ativo: dados fictícios carregados.">
        <mat-icon>science</mat-icon>
        <span>AMBIENTE DEMO</span>
      </div>

      <!-- Notifications Menu -->
      <button mat-icon-button [matMenuTriggerFor]="notifMenu" class="notif-btn" matTooltip="Notificações">
        <mat-icon [matBadge]="unreadCount > 0 ? unreadCount : null" matBadgeColor="warn" matBadgeSize="small">
          notifications
        </mat-icon>
      </button>

      <mat-menu #notifMenu="matMenu" class="notifications-menu" xPosition="before">
        <div class="notif-header" (click)="$event.stopPropagation()">
          <span class="title">Notificações</span>
          <button mat-button class="mark-all-btn" *ngIf="unreadCount > 0" (click)="markAllAsRead()">
            Marcar lidas
          </button>
        </div>
        <mat-divider></mat-divider>
        <div class="notif-list" (click)="$event.stopPropagation()">
          <div *ngFor="let notif of notifications" class="notif-item" [class.unread]="!notif.is_read" (click)="onNotificationClick(notif)">
            <mat-icon class="notif-icon">info</mat-icon>
            <div class="notif-text">
              <span class="notif-title">{{ notif.title }}</span>
              <span class="notif-msg">{{ notif.message }}</span>
              <span class="notif-time">{{ notif.created_at | date:'dd/MM HH:mm' }}</span>
            </div>
          </div>
          <div *ngIf="notifications.length === 0" class="notif-empty">
            <mat-icon>notifications_none</mat-icon>
            <p>Nenhuma notificação no momento</p>
          </div>
        </div>
      </mat-menu>
      
      <!-- User Profile Menu -->
      <ng-container *ngIf="authService.currentUser$ | async as user">
        <div class="user-pill" [matMenuTriggerFor]="userMenu">
          <div class="avatar-circle">
            {{ user.email.slice(0, 2).toUpperCase() }}
          </div>
          <div class="user-meta">
            <span class="user-email">{{ user.email }}</span>
            <span class="user-role">{{ user.is_admin ? 'Administrador' : 'Colaborador' }}</span>
          </div>
          <mat-icon class="arrow-icon">keyboard_arrow_down</mat-icon>
        </div>

        <mat-menu #userMenu="matMenu" xPosition="before">
          <div class="menu-user-info">
            <strong>{{ user.email }}</strong>
            <span>{{ user.is_admin ? 'Acesso Total (Admin)' : 'Perfil Padrão' }}</span>
          </div>
          <mat-divider></mat-divider>
          <a mat-menu-item routerLink="/change-password">
            <mat-icon>lock_reset</mat-icon>
            <span>Alterar Senha</span>
          </a>
          <mat-divider></mat-divider>
          <button mat-menu-item (click)="logout()" class="logout-btn">
            <mat-icon color="warn">logout</mat-icon>
            <span>Sair do Sistema</span>
          </button>
        </mat-menu>
      </ng-container>
    </mat-toolbar>
  `,
  styles: [`
    .header-toolbar {
      background-color: #ffffff;
      color: #1e293b;
      height: 64px;
      padding: 0 20px;
      border-bottom: 1px solid #e2e8f0;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
      position: relative;
      z-index: 10;
      display: flex;
      align-items: center;

      .menu-btn {
        color: #475569;
      }

      .spacer {
        flex: 1 1 auto;
      }

      .demo-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background-color: #fef3c7;
        color: #92400e;
        border: 1px solid #fde68a;
        padding: 4px 12px;
        border-radius: 16px;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.5px;
        margin-right: 16px;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);

        mat-icon {
          font-size: 16px;
          width: 16px;
          height: 16px;
          color: #d97706;
        }
      }

      .notif-btn {
        margin-right: 12px;
        color: #64748b;

        &:hover {
          color: #1e293b;
        }
      }

      .user-pill {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 4px 10px 4px 6px;
        border-radius: 24px;
        cursor: pointer;
        transition: background-color 0.15s ease-in-out;
        border: 1px solid transparent;

        &:hover {
          background-color: #f8fafc;
          border-color: #e2e8f0;
        }

        .avatar-circle {
          width: 32px;
          height: 32px;
          border-radius: 50%;
          background: #eff6ff;
          color: #2563eb;
          font-weight: 700;
          font-size: 12px;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .user-meta {
          display: flex;
          flex-direction: column;
          line-height: 1.2;

          .user-email {
            font-size: 13px;
            font-weight: 500;
            color: #1e293b;
          }

          .user-role {
            font-size: 11px;
            color: #64748b;
          }
        }

        .arrow-icon {
          color: #94a3b8;
          font-size: 18px;
          width: 18px;
          height: 18px;
        }
      }
    }

    .notif-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 16px;
      min-width: 300px;

      .title {
        font-weight: 600;
        font-size: 14px;
        color: #1e293b;
      }

      .mark-all-btn {
        font-size: 12px;
        color: #2563eb;
        padding: 0 6px;
        height: 28px;
        line-height: 28px;
      }
    }

    .notif-list {
      max-height: 360px;
      overflow-y: auto;

      .notif-item {
        display: flex;
        gap: 12px;
        padding: 10px 16px;
        border-bottom: 1px solid #f1f5f9;
        cursor: pointer;
        transition: background-color 0.15s ease;

        &:hover {
          background-color: #f8fafc;
        }

        &.unread {
          background-color: #eff6ff;
        }

        .notif-icon {
          color: #3b82f6;
          font-size: 20px;
          width: 20px;
          height: 20px;
          margin-top: 2px;
        }

        .notif-text {
          display: flex;
          flex-direction: column;

          .notif-title {
            font-size: 13px;
            font-weight: 600;
            color: #1e293b;
          }

          .notif-msg {
            font-size: 12px;
            color: #475569;
            margin-top: 2px;
          }

          .notif-time {
            font-size: 11px;
            color: #94a3b8;
            margin-top: 4px;
          }
        }
      }

      .notif-empty {
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 24px 16px;
        color: #94a3b8;

        mat-icon {
          font-size: 32px;
          width: 32px;
          height: 32px;
          margin-bottom: 6px;
        }

        p {
          margin: 0;
          font-size: 13px;
        }
      }
    }

    .menu-user-info {
      padding: 12px 16px;
      display: flex;
      flex-direction: column;

      strong {
        font-size: 14px;
        color: #1e293b;
      }

      span {
        font-size: 12px;
        color: #64748b;
        margin-top: 2px;
      }
    }
  `]
})
export class HeaderComponent implements OnInit {
  @Output() toggleSidenav = new EventEmitter<void>();

  authService = inject(AuthService);
  private notificationsService = inject(NotificationsService);
  private http = inject(HttpClient);

  notifications: Notification[] = [];
  unreadCount: number = 0;
  isDemoMode: boolean = false;

  ngOnInit(): void {
    this.loadNotifications();
    this.checkDemoStatus();
    this.notificationsService.newNotification$.subscribe((notif) => {
      this.notifications.unshift(notif);
      this.calculateUnread();
    });
  }

  checkDemoStatus(): void {
    this.http.get<{ is_demo_mode: boolean }>('/api/v1/system/demo/status').subscribe({
      next: (res) => {
        this.isDemoMode = !!res?.is_demo_mode;
      },
      error: () => {
        this.isDemoMode = false;
      }
    });
  }

  loadNotifications(): void {
    this.notificationsService.getNotifications(10).subscribe({
      next: (list) => {
        this.notifications = list;
        this.calculateUnread();
      },
      error: () => {}
    });
  }

  calculateUnread(): void {
    this.unreadCount = this.notifications.filter((n) => !n.is_read).length;
  }

  onNotificationClick(notif: Notification): void {
    if (!notif.is_read) {
      this.notificationsService.markAsRead(notif.id).subscribe(() => {
        notif.is_read = true;
        this.calculateUnread();
      });
    }
  }

  markAllAsRead(): void {
    this.notificationsService.markAllAsRead().subscribe(() => {
      this.notifications.forEach((n) => (n.is_read = true));
      this.calculateUnread();
    });
  }

  logout(): void {
    this.authService.logout();
  }
}
