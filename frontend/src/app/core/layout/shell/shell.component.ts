import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterOutlet, Router } from '@angular/router';
import { MatSidenavModule } from '@angular/material/sidenav';
import { Subscription } from 'rxjs';

import { HeaderComponent } from '../header/header.component';
import { SidebarComponent } from '../sidebar/sidebar.component';
import { AuthService } from '../../auth/auth.service';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [
    CommonModule,
    RouterOutlet,
    MatSidenavModule,
    HeaderComponent,
    SidebarComponent
  ],
  template: `
    <mat-sidenav-container class="sidenav-container">
      <mat-sidenav #sidenav mode="side" opened class="sidenav">
        <app-sidebar></app-sidebar>
      </mat-sidenav>
      
      <mat-sidenav-content>
        <app-header (toggleSidenav)="sidenav.toggle()"></app-header>
        <main class="main-content">
          <router-outlet></router-outlet>
        </main>
      </mat-sidenav-content>
    </mat-sidenav-container>
  `,
  styles: [`
    .sidenav-container {
      height: 100vh;
    }
    
    .sidenav {
      width: 250px;
      background-color: #fafafa;
    }
    
    .main-content {
      padding: 24px;
      height: calc(100vh - 64px);
      overflow: auto;
      box-sizing: border-box;
      background-color: #f5f5f5;
    }
  `]
})
export class ShellComponent implements OnInit, OnDestroy {
  authService = inject(AuthService);
  private router = inject(Router);
  private sub?: Subscription;

  ngOnInit() {
    this.sub = this.authService.currentUser$.subscribe(user => {
      if (user?.must_change_password) {
        this.router.navigate(['/change-password']);
      }
    });
  }

  ngOnDestroy() {
    this.sub?.unsubscribe();
  }
}
