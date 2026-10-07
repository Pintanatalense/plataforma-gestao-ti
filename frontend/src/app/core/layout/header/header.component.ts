import { Component, EventEmitter, inject, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatMenuModule } from '@angular/material/menu';
import { MatDividerModule } from '@angular/material/divider';
import { AuthService } from '../../auth/auth.service';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [
    CommonModule,
    MatToolbarModule,
    MatIconModule,
    MatButtonModule,
    MatMenuModule,
    MatDividerModule
  ],
  template: `
    <mat-toolbar color="primary" class="header-toolbar">
      <button mat-icon-button (click)="toggleSidenav.emit()" aria-label="Toggle sidenav">
        <mat-icon>menu</mat-icon>
      </button>
      
      <span class="spacer"></span>
      
      <ng-container *ngIf="authService.currentUser$ | async as user">
        <span class="user-email">{{ user.email }}</span>
        <button mat-icon-button [matMenuTriggerFor]="menu" aria-label="Menu de usuário">
          <mat-icon>account_circle</mat-icon>
        </button>
        <mat-menu #menu="matMenu">
          <button mat-menu-item>
            <mat-icon>person</mat-icon>
            <span>Meu Perfil</span>
          </button>
          <mat-divider></mat-divider>
          <button mat-menu-item (click)="logout()">
            <mat-icon>exit_to_app</mat-icon>
            <span>Sair</span>
          </button>
        </mat-menu>
      </ng-container>
    </mat-toolbar>
  `,
  styles: [`
    .header-toolbar {
      box-shadow: 0 3px 5px -1px rgba(0,0,0,.2), 0 6px 10px 0 rgba(0,0,0,.14), 0 1px 18px 0 rgba(0,0,0,.12);
      z-index: 2;
      position: relative;
    }
    .spacer {
      flex: 1 1 auto;
    }
    .user-email {
      font-size: 14px;
      margin-right: 8px;
    }
  `]
})
export class HeaderComponent {
  @Output() toggleSidenav = new EventEmitter<void>();
  authService = inject(AuthService);

  logout() {
    this.authService.logout();
  }
}
