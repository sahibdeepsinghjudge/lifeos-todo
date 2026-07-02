User enters propmts.
Classify the prompt as simple (can be handled directly using single agent) or complex (needs multiple agents).
if task is simple create task and return response else start agent work
Agent work:

1. Analyze the prompt.
2. Decide the role of the agent based on the user's input. Use daily_planner for daily tasks, gym_trainer for fitness tasks, budget_planner for financial tasks, house_maker for home tasks, analyst for analysis tasks, product_manager for project management tasks, and general for general tasks. If no role matches use general
3. Use available set of tools where required and do not rely on the general data, clairfy from the user when required
4. A simple task for us is straight forward tasks which has no dependecy on any other task. This can be creating a todo item, changing the time of the todo, making it repetive or updating the description of the task.

If task is complex which means tasks depnds on each other and a prompt has multiple things like researching the web asking questions and then using the results to create a task and then make sub tasks in it then use multi agents and personas.

1. Analyse the propmt
2. break to seprate independent tasks
3. decide a workflow loop like if user wants to prepare grocery list to make rajma, the agent will search web -> get ingredients -> create task -> add these items as subtasks.
   This is the whole workflow.
4. reply accordingly to the user. and only change the mode from complex to simple when the task is done.

Use light model for simple replies and direct tool usage.
