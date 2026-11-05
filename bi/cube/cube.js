// Access control lives in the semantic layer, not in each dashboard: every query, from Superset (SQL API) or
// the REST API, passes through queryRewrite with the caller's security context.
//
//   role "admin"    -> everything
//   role "analyst"  -> trip data filtered to the analyst's borough (row-level security)
//   no role         -> refused
//
// SQL API logins come from .env (CUBE_SQL_*); REST callers send a JWT signed with CUBEJS_API_SECRET whose
// payload carries the same {role, borough} context.

const SQL_USERS = {
  [process.env.CUBE_SQL_ADMIN_USER]: {
    password: process.env.CUBE_SQL_ADMIN_PASSWORD,
    securityContext: { role: "admin" },
  },
  [process.env.CUBE_SQL_ANALYST_USER]: {
    password: process.env.CUBE_SQL_ANALYST_PASSWORD,
    securityContext: { role: "analyst", borough: process.env.CUBE_SQL_ANALYST_BOROUGH },
  },
};

// Members whose rows belong to a borough, and the borough member to filter on. A query touching any of them
// gets the analyst's filter (views and cubes are filtered through their own member names).
const SCOPES = [
  { prefixes: ["taxi_operations."], borough: "taxi_operations.pickup_zones_borough" },
  { prefixes: ["taxi_trips.", "pickup_zones."], borough: "pickup_zones.borough" },
];

function members(query) {
  return [
    ...(query.measures || []),
    ...(query.dimensions || []),
    ...(query.segments || []),
    ...(query.timeDimensions || []).map((t) => t.dimension),
    ...(query.filters || []).flatMap(function walk(f) {
      return f.member ? [f.member] : [...(f.and || []), ...(f.or || [])].flatMap(walk);
    }),
  ];
}

module.exports = {
  checkSqlAuth: async (req, user, password) => {
    const entry = SQL_USERS[user];
    if (!user || !entry || !entry.password) {
      throw new Error(`Unknown Cube SQL user: ${user}`);
    }
    return { password: entry.password, securityContext: entry.securityContext };
  },

  queryRewrite: (query, { securityContext }) => {
    const ctx = securityContext || {};
    if (ctx.role === "admin") return query;
    if (ctx.role !== "analyst" || !ctx.borough) {
      throw new Error("Access denied: no role in the security context");
    }
    const used = members(query);
    for (const scope of SCOPES) {
      if (used.some((m) => scope.prefixes.some((p) => m.startsWith(p)))) {
        query.filters = [
          ...(query.filters || []),
          { member: scope.borough, operator: "equals", values: [ctx.borough] },
        ];
      }
    }
    return query;
  },
};
