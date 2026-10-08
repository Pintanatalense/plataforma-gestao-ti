import { Routes } from '@angular/router';
import { LoginComponent } from './features/auth/login/login.component';
import { ShellComponent } from './core/layout/shell/shell.component';
import { inject } from '@angular/core';
import { AuthService } from './core/auth/auth.service';
import { Router } from '@angular/router';
import { setupGuard } from './core/auth/setup.guard';

const authGuard = () => {
  const authService = inject(AuthService);
  const router = inject(Router);
  
  if (authService.token) {
    return true;
  }
  
  router.navigate(['/login']);
  return false;
};

export const routes: Routes = [
  {
    path: 'setup',
    loadComponent: () => import('./features/setup/setup.component').then(m => m.SetupComponent),
    canActivate: [setupGuard]
  },
  {
    path: 'login',
    component: LoginComponent
  },
  {
    path: 'change-password',
    loadComponent: () => import('./features/auth/change-password/change-password.component').then(m => m.ChangePasswordComponent),
    canActivate: [authGuard]
  },
  {
    path: '',
    component: ShellComponent,
    canActivate: [authGuard],
    children: [
      {
        path: '',
        redirectTo: 'dashboard',
        pathMatch: 'full'
      },
      {
        path: 'dashboard',
        loadComponent: () => import('./features/dashboard/dashboard.component').then(m => m.Dashboard)
      },
      {
        path: 'organization',
        loadComponent: () => import('./features/organization/unit-list/unit-list.component').then(m => m.UnitList)
      },
      {
        path: 'organization/sectors',
        loadComponent: () => import('./features/organization/sector-list/sector-list.component').then(m => m.SectorList)
      },
      {
        path: 'organization/employees',
        loadComponent: () => import('./features/organization/employee-list/employee-list.component').then(m => m.EmployeeList)
      },
      {
        path: 'identity/users',
        loadComponent: () => import('./features/identity/user-list/user-list.component').then(m => m.UserList)
      },
      {
        path: 'identity/roles',
        loadComponent: () => import('./features/identity/role-list/role-list.component').then(m => m.RoleList)
      },
      {
        path: 'service-desk',
        loadComponent: () => import('./features/service-desk/ticket-list/ticket-list.component').then(m => m.TicketListComponent)
      },
      {
        path: 'service-desk/new',
        loadComponent: () => import('./features/service-desk/ticket-create/ticket-create.component').then(m => m.TicketCreateComponent)
      },
      {
        path: 'service-desk/:id',
        loadComponent: () => import('./features/service-desk/ticket-detail/ticket-detail.component').then(m => m.TicketDetailComponent)
      }
    ]
  },
  {
    path: '**',
    redirectTo: ''
  }
];
